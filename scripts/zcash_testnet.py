#!/usr/bin/env python3
"""Explicit local testnet wallet demo. No keys are read, printed, or stored here."""
from __future__ import annotations
import argparse
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time

import httpx
from veilagent.providers.zcash import ZcashClient, ZcashError, payment_uri, validate_payment


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous = os.umask(0o077)
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        os.umask(previous)


async def main(args: argparse.Namespace) -> None:
    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    signing = ZcashClient(args.signing_url)
    watcher = ZcashClient(args.watch_url, account_id=state.get("watch_account", 1))
    if args.command == "setup":
        if state:
            raise ZcashError("SETUP_EXISTS", "State already exists. Reuse it; do not create duplicate demo accounts.")
        tip = (await signing.query("{ currentHeight }"))["currentHeight"]
        birth = max(1, tip - 10)
        state = {"birth_height": birth, "network": "testnet"}
        for name in ("payer", "merchant"):
            data = await signing.query("mutation($account: NewAccount!) { createAccount(newAccount: $account) }",
                                       {"account": {"name": f"veilagent-{name}", "key": "", "useInternal": True,
                                                    "aindex": 0, "birth": birth}})
            account_id = data["createAccount"]
            state[f"{name}_account"] = account_id
            client = ZcashClient(args.signing_url, account_id)
            state[f"{name}_address"] = await client.address()
        merchant = ZcashClient(args.signing_url, state["merchant_account"])
        # UFVK stays in local memory and the receiving wallet database. It is never printed.
        key = (await merchant.query("query($id: Int!) { unifiedFullViewingKey(idAccount: $id) }",
                                    {"id": merchant.account_id}))["unifiedFullViewingKey"]
        if not isinstance(key, str) or not key.startswith("uviewtest"):
            raise ZcashError("TESTNET_VIEWING_KEY", "Wallet returned a non-testnet viewing key.")
        data = await watcher.query("mutation($account: NewAccount!) { createAccount(newAccount: $account) }",
                                   {"account": {"name": "veilagent-watch-only", "key": key, "useInternal": True,
                                                "aindex": 0, "birth": birth}})
        state["watch_account"] = data["createAccount"]
        del key
        save(state_path, state)
        print(json.dumps(state, indent=2))
        return
    if not state or state.get("network") != "testnet":
        raise ZcashError("SETUP_REQUIRED", "Run setup against fresh testnet wallet databases first.")
    payer = ZcashClient(args.signing_url, state["payer_account"])
    watcher = ZcashClient(args.watch_url, state["watch_account"], confirmations=args.confirmations)
    if await payer.address() != state["payer_address"] or await watcher.address() != state["merchant_address"]:
        raise ZcashError("ACCOUNT_CHANGED", "Wallet accounts differ from the saved setup.")
    if args.command == "faucet":
        if state.get("faucet_attempted"):
            raise ZcashError("FAUCET_ALREADY_REQUESTED", "One faucet request was already attempted; use faucet-status.")
        state["faucet_attempted"] = True
        save(state_path, state)  # Reserve before request; a timeout must not cause a repeated claim.
        async with httpx.AsyncClient(timeout=40, follow_redirects=False) as client:
            response = await client.post("https://fauzec.com/api/v1/claim",
                                         json={"network": "testnet", "address": state["payer_address"]})
            if response.status_code != 200:
                raise ZcashError("FAUCET_REFUSED", "Faucet refused the request. Ask a mentor; do not retry automatically.")
            result = response.json()
        state["faucet_request_id"] = result.get("request_id")
        save(state_path, state)
        print(json.dumps({"request_id": state["faucet_request_id"], "state": result.get("state")}))
    elif args.command == "faucet-status":
        request_id = state.get("faucet_request_id")
        if not isinstance(request_id, str) or not request_id.isalnum():
            raise ZcashError("FAUCET_ID", "No faucet request ID is saved; inspect the faucet manually.")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(f"https://fauzec.com/api/v1/status/testnet/{request_id}")
            response.raise_for_status()
            result = response.json()
        allowed = ("request_id", "state", "outcome", "error_code", "txid", "transaction_id")
        safe = {k: result[k] for k in allowed if k in result}
        state["faucet_status"] = safe
        save(state_path, state)
        print(json.dumps(safe, indent=2))
    elif args.command == "send":
        validate_payment(args.amount_zats, args.memo)
        if args.amount_zats > 100_000:
            raise ZcashError("DEMO_CAP", "Demo sender cap is 100,000 zats (0.001 TAZ) per state file.")
        if state.get("send_attempted"):
            raise ZcashError("SEND_ALREADY_ATTEMPTED", "Send was already attempted. Watch for confirmation; do not replay.")
        await payer.synchronize()
        state.update({"send_attempted": True, "memo": args.memo, "amount_zats": args.amount_zats})
        save(state_path, state)
        amount = format(Decimal(args.amount_zats) / 100_000_000, ".8f")
        # No fee override: the wallet SDK computes the transaction fee.
        query = (f"mutation {{ pay(idAccount: {payer.account_id}, payment: {{ recipients: [{{ address: "
                 f"{json.dumps(state['merchant_address'])}, amount: {amount}, memo: {json.dumps(args.memo)} "
                 "}], srcPools: 10, confirmations: 1 }) }")
        result = await payer.query(query)
        txid = result.get("pay")
        if not isinstance(txid, str) or len(txid) != 64:
            raise ZcashError("SEND_UNCERTAIN", "Wallet did not return a transaction ID. Do not retry automatically.")
        state["broadcast_txid"] = txid
        save(state_path, state)
        print(json.dumps({"status": "broadcast_only", "txid": txid,
                          "payment_uri": payment_uri(state["merchant_address"], args.amount_zats, args.memo)}))
    elif args.command == "watch":
        memo = args.memo or state.get("memo")
        amount = args.amount_zats or state.get("amount_zats")
        deadline = time.monotonic() + args.timeout
        while True:
            receipt = await watcher.find_payment(memo, amount)
            if receipt:
                state["verified_receipt"] = receipt
                save(state_path, state)
                print(json.dumps(receipt, indent=2))
                return
            if time.monotonic() >= deadline:
                raise ZcashError("NOT_CONFIRMED", "No matching confirmed shielded payment yet.")
            await asyncio.sleep(10)


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "faucet", "faucet-status", "send", "watch"))
    parser.add_argument("--signing-url", default="http://127.0.0.1:8001/graphql")
    parser.add_argument("--watch-url", default="http://127.0.0.1:8000/graphql")
    parser.add_argument("--state", default=".local/zcash/demo-state.json")
    parser.add_argument("--memo")
    parser.add_argument("--amount-zats", type=int)
    parser.add_argument("--confirmations", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    try:
        asyncio.run(main(args))
    except (ZcashError, httpx.HTTPError) as error:
        code = error.code if isinstance(error, ZcashError) else "NETWORK_ERROR"
        message = error.message if isinstance(error, ZcashError) else "Network request failed; do not retry a side effect blindly."
        print(json.dumps({"error": code, "message": message}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()

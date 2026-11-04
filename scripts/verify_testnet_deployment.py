#!/usr/bin/env python3
"""Explicitly send one capped TAZ payment and verify the deployed private checkout.

This is a live testnet operation, never part of the automated test suite. Resume
with the same state file after an interruption; reserved sends are never retried.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx

from pegasus.infrastructure.providers.zcash_client import (
    TXID_RE,
    ZcashClient,
    ZcashError,
    payment_uri,
    validate_payment,
)

MAX_DEMO_ZATS = 100_000


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, data: dict, *, public: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out, indent=2, allow_nan=False)
        out.write("\n")
    temporary.chmod(0o644 if public else 0o600)
    temporary.replace(path)


def fail(message: str) -> None:
    raise ValueError(message)


def base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        fail("Use the exact public HTTPS origin, without credentials, path, query or fragment.")
    return value.rstrip("/")


def response_code(response: httpx.Response) -> str | None:
    try:
        error = response.json().get("error")
        return error.get("code") if isinstance(error, dict) else None
    except (ValueError, AttributeError):
        return None


def expect(response: httpx.Response, status: int, code: str | None = None) -> None:
    if response.status_code != status or (code and response_code(response) != code):
        fail(f"Unexpected HTTP result: expected {status} {code or ''}; got {response.status_code}.")


def safe_order(order: dict) -> dict:
    names = (
        "id", "memo", "address", "amount_zats", "payment_uri", "status", "created_at",
        "payment", "entitlement_expires_at",
    )
    return {name: order[name] for name in names if name in order}


async def verify(args: argparse.Namespace) -> None:
    origin = base_url(args.base_url)
    state_path = Path(args.state)
    evidence_path = Path(args.evidence)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state and state.get("base_url") != origin:
        fail("State belongs to a different deployment; do not reuse it for another origin.")
    if not state:
        if evidence_path.exists():
            fail("Evidence already exists. Choose a new evidence path for another explicitly intended run.")
        state = {
            "network": "zcash-public-testnet", "base_url": origin,
            "evidence_path": str(evidence_path.resolve()),
            "started_at": timestamp(), "checks": {},
        }
        save(state_path, state)
    if state.get("evidence_path") != str(evidence_path.resolve()):
        fail("State belongs to a different evidence path; resume with its original --evidence value.")
    if state.get("completed_at"):
        publish_evidence(state, evidence_path)
        return
    settings = dotenv_values(args.env_file)
    token = os.environ.get("OWNER_TOKEN") or settings.get("OWNER_TOKEN")
    if not token or len(token) < 32:
        fail("A configured local OWNER_TOKEN is required; it will not be printed or stored.")
    setup = json.loads(Path(args.wallet_state).read_text())
    if setup.get("network") != "testnet":
        fail("The wallet setup must explicitly identify public testnet.")
    payer = ZcashClient(args.signing_url, setup["payer_account"])
    if await payer.address() != setup["payer_address"]:
        fail("Payer account no longer matches the saved testnet setup.")
    required_confirmations = int(settings.get("ZCASH_CONFIRMATIONS") or "1")
    state["birth_height"] = setup["birth_height"]
    state["confirmations_required"] = required_confirmations
    save(state_path, state)
    headers = {"Authorization": "Bearer " + token, "Origin": origin}
    async with httpx.AsyncClient(timeout=150, follow_redirects=False, trust_env=False) as client:
        health = await client.get(origin + "/health")
        expect(health, 200)
        config_response = await client.get(origin + "/api/config")
        expect(config_response, 200)
        config = config_response.json()
        if config.get("zcash_configured") is not True:
            fail("The deployed watch-only testnet merchant is not configured.")
        state["checks"]["public_health"] = {"http_status": health.status_code}
        state["bitrefill_configured"] = config.get("bitrefill_configured")
        missing_auth = await client.post(origin + "/api/private/orders/unknown/refresh", json={})
        expect(missing_auth, 401, "UNAUTHORIZED")
        state["checks"]["missing_authentication"] = {"http_status": 401, "code": "UNAUTHORIZED"}
        foreign = await client.get(origin + "/health", headers={"Origin": "https://foreign.invalid"})
        expect(foreign, 403, "ORIGIN_DENIED")
        state["checks"]["foreign_origin"] = {"http_status": 403, "code": "ORIGIN_DENIED"}
        save(state_path, state)

        if "order" not in state:
            if state.get("create_attempted"):
                fail("Order creation is ambiguous. Inspect the deployed database; do not create another automatically.")
            state["create_attempted"] = True
            save(state_path, state)
            response = await client.post(origin + "/api/private/orders", headers=headers, json={})
            expect(response, 200)
            state["order"] = safe_order(response.json())
            state["checks"]["create_order"] = {"http_status": 200}
            save(state_path, state)
        order = state["order"]
        if not re.fullmatch(r"zo_[0-9a-f]{32}", order.get("id", "")):
            fail("The server returned an unexpected order identifier.")
        validate_payment(order.get("amount_zats"), order.get("memo"))
        if order["address"] != setup["merchant_address"] or order["amount_zats"] != MAX_DEMO_ZATS:
            fail("Refusing payment: deployed receiver or amount differs from the known 0.001 TAZ demo.")
        if order["payment_uri"] != payment_uri(order["address"], order["amount_zats"], order["memo"]):
            fail("The payment URI does not match the exact order terms.")
        path = origin + "/api/private/orders/" + order["id"]
        if not state.get("send_attempted"):
            if order["status"] != "AWAITING_PAYMENT":
                fail("A fresh order must await payment.")
            response = await client.post(path + "/redeem", headers=headers, json={})
            expect(response, 409, "NOT_REDEEMABLE")
            state["checks"]["early_redemption"] = {"http_status": 409, "code": "NOT_REDEEMABLE"}
            response = await client.post(path + "/refresh", headers=headers, json={})
            expect(response, 200)
            unpaid = response.json()
            if unpaid.get("status") != "AWAITING_PAYMENT" or unpaid.get("payment") is not None:
                fail("Fresh unpaid order was incorrectly fulfilled.")
            state["checks"]["unpaid_refresh"] = {"http_status": 200, "status": "AWAITING_PAYMENT"}
            save(state_path, state)
            await payer.synchronize()
            state["send_attempted"] = True
            state["send_reserved_at"] = timestamp()
            save(state_path, state)
            amount = format(Decimal(order["amount_zats"]) / 100_000_000, ".8f")
            query = (
                f"mutation {{ pay(idAccount: {payer.account_id}, payment: {{ recipients: [{{ address: "
                f"{json.dumps(order['address'])}, amount: {amount}, memo: {json.dumps(order['memo'])} "
                "}], srcPools: 10, confirmations: 1 }) }"
            )
            result = await payer.query(query)
            txid = result.get("pay")
            if not isinstance(txid, str) or not TXID_RE.fullmatch(txid):
                fail("Broadcast result is ambiguous. Inspect the payer wallet; never resend automatically.")
            state["broadcast_txid"] = txid.lower()
            state["broadcast_at"] = timestamp()
            save(state_path, state)
            print(json.dumps({"status": "broadcast_only", "txid": txid.lower()}), flush=True)
        if not state.get("broadcast_txid"):
            fail("A send was reserved without a known txid. Reconcile the payer wallet before continuing.")

        if "confirmed_order" not in state:
            deadline = time.monotonic() + args.timeout
            while True:
                response = await client.post(path + "/refresh", headers=headers, json={})
                expect(response, 200)
                observed = response.json()
                if observed.get("status") == "CONFIRMED":
                    receipt = observed.get("payment") or {}
                    if (
                        receipt.get("txid") != state["broadcast_txid"]
                        or receipt.get("amount_zats") != order["amount_zats"]
                        or receipt.get("pool") not in (1, 3)
                        or type(receipt.get("height")) is not int
                        or receipt["height"] <= 0
                        or type(receipt.get("confirmations")) is not int
                        or receipt["confirmations"] < required_confirmations
                        or any(observed.get(k) != order[k] for k in ("id", "memo", "address", "amount_zats"))
                    ):
                        fail("The receiving watcher's confirmed payment does not match the exact transaction.")
                    state["confirmed_order"] = safe_order(observed)
                    state["confirmed_at"] = timestamp()
                    state["checks"]["confirmed_refresh"] = {"http_status": 200, "status": "CONFIRMED"}
                    save(state_path, state)
                    print(json.dumps({"status": "confirmed", "receipt": receipt}), flush=True)
                    break
                if observed.get("status") != "AWAITING_PAYMENT":
                    fail("The pending order entered an unexpected state.")
                if time.monotonic() >= deadline:
                    fail("Confirmation timed out. Resume with the same state file; the payment will not be resent.")
                await asyncio.sleep(10)
        if "redemption" not in state:
            if state.get("redemption_attempted"):
                fail("Redemption response is ambiguous. Inspect the existing order; do not claim success.")
            state["redemption_attempted"] = True
            save(state_path, state)
            response = await client.post(path + "/redeem", headers=headers, json={})
            expect(response, 200)
            if not isinstance(response.json().get("content"), str) or not response.json()["content"]:
                fail("Redemption did not return the protected resource.")
            state["redemption"] = {"http_status": 200, "resource_returned": True, "observed_at": timestamp()}
            save(state_path, state)
        response = await client.post(path + "/redeem", headers=headers, json={})
        expect(response, 409, "NOT_REDEEMABLE")
        state["checks"]["redemption_replay"] = {"http_status": 409, "code": "NOT_REDEEMABLE"}
        response = await client.post(path + "/refresh", headers=headers, json={})
        expect(response, 200)
        if response.json().get("status") != "REDEEMED":
            fail("The server did not persist the redeemed order state.")
        state["checks"]["redeemed_refresh"] = {"http_status": 200, "status": "REDEEMED"}
        state["completed_at"] = timestamp()
        save(state_path, state)

    publish_evidence(state, evidence_path)


def publish_evidence(state: dict, evidence_path: Path) -> None:
    """Publish only a completed observation; safely resume after an interrupted file write."""
    order = state["order"]
    origin = state["base_url"]
    evidence = {
        "network": state["network"], "base_url": origin,
        "started_at": state["started_at"], "verified_at": state["completed_at"],
        "order_id": order["id"], "memo": order["memo"], "amount_zats": order["amount_zats"],
        "recipient": order["address"], "birth_height": state["birth_height"],
        "broadcast_at": state["broadcast_at"], "confirmed_at": state["confirmed_at"],
        "receipt": state["confirmed_order"]["payment"],
        "confirmations_required": state["confirmations_required"],
        "explorer_url": "https://zexplorer.app/testnet/tx/" + state["broadcast_txid"],
        "checks": state["checks"], "redemption": state["redemption"],
        "lightwallet_server": "https://testnet.zec.rocks:443",
        "limits": (
            "A real capped public-testnet payment was sent from the local disposable payer. "
            "The deployed HTTP application's independent watch-only receiver verified the mined note, "
            "exact memo and amount. The public explorer alone cannot reveal shielded amount or memo. "
            "Cloudflare terminates HTTPS and can see application requests; bearer credentials are omitted "
            "from this receipt. This temporary demo requires its local processes to remain running. "
            "Bitrefill settlement was not executed."
        ),
    }
    if evidence_path.exists():
        previous = json.loads(evidence_path.read_text())
        if previous != evidence:
            fail("Existing evidence differs from the completed run; it will not be overwritten.")
        print(json.dumps({"status": "already_verified", "evidence": str(evidence_path)}))
        return
    save(evidence_path, evidence, public=True)
    print(json.dumps({"status": "verified", "evidence": str(evidence_path), "txid": state["broadcast_txid"]}))


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--state", default=".local/zcash/deployment-verification.json")
    parser.add_argument("--wallet-state", default=".local/zcash/demo-state.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--signing-url", default="http://127.0.0.1:8001/graphql")
    parser.add_argument("--evidence", default="docs/evidence/deployed-testnet-checkout.json")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        state_path = Path(args.state)
        state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(state_path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("Another verification owns this state file; do not start a concurrent payment.")
            asyncio.run(verify(args))
    except (ValueError, KeyError, OSError, httpx.HTTPError, ZcashError) as error:
        # Never echo raw HTTP request headers, provider errors, or local configuration.
        message = (
            error.message if isinstance(error, ZcashError)
            else str(error) if isinstance(error, ValueError)
            else "Verification interrupted by an I/O or schema failure. Resume the same state; inspect before retrying."
        )
        print(json.dumps({"status": "incomplete", "message": message}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()

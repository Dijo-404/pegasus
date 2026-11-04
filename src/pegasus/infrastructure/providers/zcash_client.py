"""Read-only, loopback-only public-testnet payment detection via zkool_graphql.

The wallet service is trusted; this adapter cannot independently validate its chain.
Run the wallet with -C 1 and https://testnet.zec.rocks:443 as documented.
"""

from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
import ipaddress
import re
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from pegasus.domain.exceptions import IntegrationError

ZATS_PER_TAZ = 100_000_000
TXID_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ZcashError(IntegrationError):
    """Safe wallet-adapter failure without upstream wallet response contents."""


def validate_wallet_url(url: str) -> str:
    parsed = urlsplit(url)
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if (
        parsed.scheme != "http"
        or not local
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != "/graphql"
    ):
        raise ZcashError("WALLET_URL", "Use a loopback http://127.0.0.1:<port>/graphql wallet endpoint.")
    return url


def validate_testnet_address(address: str) -> str:
    # Receiver support is checked separately against the trusted wallet's decoded fields.
    if not isinstance(address, str) or not re.fullmatch(r"utest1[0-9a-z]{20,1000}", address):
        raise ZcashError("TESTNET_ADDRESS", "A public-testnet unified address is required.")
    return address


def zats_from_decimal(value: Any) -> int:
    try:
        if isinstance(value, (bool, float)):
            raise ValueError("Lossy decimal")
        amount = Decimal(str(value)) * ZATS_PER_TAZ
        if not amount.is_finite() or amount != amount.to_integral_value() or amount < 0:
            raise ValueError("Invalid amount")
        return int(amount)
    except (ValueError, InvalidOperation, TypeError, OverflowError):
        raise ZcashError("WALLET_SCHEMA", "Wallet returned an invalid decimal amount.") from None


def validate_payment(amount_zats: int, memo: str) -> None:
    if type(amount_zats) is not int or not 0 < amount_zats <= 21_000_000 * ZATS_PER_TAZ:
        raise ZcashError("INVALID_AMOUNT", "Amount must be a positive integer in zatoshis.")
    if not isinstance(memo, str) or not memo or len(memo.encode("utf-8")) > 512:
        raise ZcashError("INVALID_MEMO", "An order memo of 1–512 UTF-8 bytes is required.")


def payment_uri(address: str, amount_zats: int, memo: str) -> str:
    validate_testnet_address(address)
    validate_payment(amount_zats, memo)
    amount = format(Decimal(amount_zats) / ZATS_PER_TAZ, ".8f")
    encoded = base64.urlsafe_b64encode(memo.encode("utf-8")).decode("ascii").rstrip("=")
    return f"zcash:{address}?{urlencode({'amount': amount, 'memo': encoded})}"


class ZcashClient:
    payment_uri = staticmethod(payment_uri)

    def __init__(
        self,
        url: str = "http://127.0.0.1:8000/graphql",
        account_id: int = 1,
        confirmations: int = 1,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = validate_wallet_url(url)
        if type(account_id) is not int or account_id < 1:
            raise ZcashError("INVALID_ACCOUNT", "A positive wallet account ID is required.")
        if type(confirmations) is not int or not 1 <= confirmations <= 100:
            raise ZcashError("INVALID_CONFIRMATIONS", "Require between one and 100 confirmations.")
        self.account_id = account_id
        self.confirmations = confirmations
        self.transport = transport

    async def query(self, query: str, variables: dict | None = None) -> dict:
        """Wallet RPC helper. Never return upstream error strings or seed fields."""
        try:
            async with httpx.AsyncClient(
                timeout=120, trust_env=False, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(self.url, json={"query": query, "variables": variables or {}})
            response.raise_for_status()
            data = response.json(parse_float=Decimal)
        except (httpx.HTTPError, ValueError):
            raise ZcashError("WALLET_UNAVAILABLE", "Cannot reach the local testnet wallet service.") from None
        if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict):
            raise ZcashError(
                "WALLET_RPC", "Wallet rejected the request. Check its version and account permissions."
            )
        return data["data"]

    async def address(self) -> str:
        data = await self.query(
            "query($id: Int!) { addressByAccount(idAccount: $id) { ua sapling ironwood } }",
            {"id": self.account_id},
        )
        decoded = data.get("addressByAccount")
        if not isinstance(decoded, dict) or not (decoded.get("sapling") or decoded.get("ironwood")):
            raise ZcashError("SHIELDED_RECEIVER", "Account needs a Sapling or Ironwood receiver.")
        return validate_testnet_address(decoded.get("ua"))

    async def synchronize(self) -> int:
        data = await self.query(
            "mutation($ids: [Int!]!) { synchronize(idAccounts: $ids, fast: false) }",
            {"ids": [self.account_id]},
        )
        height = data.get("synchronize")
        if type(height) is not int or height <= 0:
            raise ZcashError("WALLET_SCHEMA", "Wallet has not synchronized a positive block height.")
        return height

    async def check(self) -> dict:
        address = await self.address()
        data = await self.query("{ currentHeight }")
        height = data.get("currentHeight")
        if type(height) is not int or height <= 0:
            raise ZcashError("WALLET_SCHEMA", "Wallet returned an invalid block height.")
        return {
            "network": "testnet",
            "address": address,
            "height": height,
            "confirmations_required": self.confirmations,
        }

    async def find_payment(self, memo: str, amount_zats: int) -> dict | None:
        validate_payment(amount_zats, memo)
        await self.address()  # Refuse accidental mainnet/regtest or Orchard-only configuration.
        synced_height = await self.synchronize()
        data = await self.query(
            "query($id: Int!) { currentHeight transactionsByAccount(idAccount: $id) "
            "{ txid height notes { pool value address scope memo } } }",
            {"id": self.account_id},
        )
        tip, transactions = data.get("currentHeight"), data.get("transactionsByAccount")
        if type(tip) is not int or tip <= 0 or not isinstance(transactions, list):
            raise ZcashError("WALLET_SCHEMA", "Wallet returned invalid transaction data.")
        # The observed sync height caps confirmations if a newer tip arrives between calls.
        tip = min(tip, synced_height)
        for tx in transactions:
            if not isinstance(tx, dict):
                raise ZcashError("WALLET_SCHEMA", "Wallet returned invalid transaction data.")
            height = tx.get("height")
            if type(height) is not int or height <= 0 or height > tip:
                continue
            confirmations = tip - height + 1
            if confirmations < self.confirmations:
                continue
            txid = tx.get("txid")
            if not isinstance(txid, str) or not TXID_RE.fullmatch(txid):
                continue
            notes = tx.get("notes")
            if not isinstance(notes, list):
                raise ZcashError("WALLET_SCHEMA", "Wallet returned invalid transaction notes.")
            received = 0
            pools = set()
            for note in notes:
                if not isinstance(note, dict):
                    raise ZcashError("WALLET_SCHEMA", "Wallet returned invalid transaction notes.")
                if (
                    type(note.get("scope")) is not int
                    or note["scope"] != 0
                    or type(note.get("pool")) is not int
                    or note["pool"] not in (1, 3)
                    or note.get("memo") != memo
                ):
                    continue
                received += zats_from_decimal(note.get("value"))
                pools.add(note["pool"])
            if received >= amount_zats:
                return {
                    "txid": txid.lower(),
                    "height": height,
                    "confirmations": confirmations,
                    "amount_zats": received,
                    "pool": next(iter(pools)) if len(pools) == 1 else "mixed",
                }
        return None

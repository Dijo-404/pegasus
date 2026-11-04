"""Explicit, single-attempt x402 v2 payments on Base Sepolia only.

Discovery is unsigned and needs neither the optional SDK nor a key. The caller
must reserve authority and budget before calling pay; this adapter never retries
a signed request. RPC receipts are trusted observations from the configured RPC,
not a locally verified chain. No automatic x402 HTTP wrappers are used.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import ipaddress
import json
import math
import os
import re
import socket
import stat
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from pegasus.domain.exceptions import IntegrationError

BASE_SEPOLIA_NETWORK = "eip155:84532"
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Circle EIP3009.sol: AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce).
AUTHORIZATION_USED_TOPIC = "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"
MAX_BODY_BYTES = 65_536
MAX_HEADER_BYTES = 32_768
MAX_PAYMENT_HEADER_BYTES = 24_576
MAX_CHALLENGE_BYTES = 16_384
RECEIPT_TIMEOUT_SECONDS = 12.0
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")
HASH_RE = re.compile(r"0x[0-9a-fA-F]{64}\Z")
ATOM_RE = re.compile(r"[1-9][0-9]{0,77}\Z")
Resolver = Callable[[str], Awaitable[list[str]]]


class X402Error(IntegrationError):
    """A fixed safe error; upstream contents, credentials and signatures are excluded."""


def _invalid(code: str = "X402_INVALID_RESPONSE") -> X402Error:
    return X402Error(code, "The external payment request could not be safely verified.")


def validate_public_https_url(url: str) -> str:
    """Validate syntax here; public DNS addresses are checked immediately before I/O."""
    try:
        if not isinstance(url, str) or len(url) > 2048 or not url.isascii():
            raise ValueError
        if (
            any(ord(character) <= 32 or ord(character) == 127 for character in url)
            or "\\" in url
            or "#" in url
        ):
            raise ValueError
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not url.startswith("https://")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.port not in (None, 443)
            or len(host) > 253
            or "." not in host
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split(".")
            )
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return url
        raise ValueError
    except (TypeError, ValueError):
        raise _invalid("X402_PUBLIC_HTTPS_REQUIRED") from None


async def _resolve(host: str) -> list[str]:
    records = await asyncio.get_running_loop().getaddrinfo(
        host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return list(dict.fromkeys(record[4][0] for record in records))


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return (
            address.is_global
            and not address.is_multicast
            and not address.is_reserved
            and not address.is_loopback
            and not address.is_link_local
            and not address.is_unspecified
            and "%" not in value
        )
    except ValueError:
        return False


class PublicHTTPSClient:
    """Resolve once, reject every nonpublic answer, and connect to one pinned IP.

    Host and TLS SNI retain the original DNS name, so certificate verification is
    still against the approved origin. Proxies, redirects and connection retries
    are disabled. Resolver/transport injection is only an offline testing seam.
    """

    def __init__(self, *, resolver: Resolver = _resolve, transport: httpx.AsyncBaseTransport | None = None):
        self._resolver = resolver
        self._transport = transport

    async def request(self, method: str, url: str, *, headers: dict | None = None, body: dict | None = None):
        validate_public_https_url(url)
        original = httpx.URL(url)
        try:
            addresses = await asyncio.wait_for(self._resolver(original.host), timeout=10)
            if not addresses or len(addresses) > 64 or not all(_public_ip(value) for value in addresses):
                raise _invalid("X402_PUBLIC_DNS_REQUIRED")
            target = original.copy_with(host=addresses[0], port=443)
            outgoing = httpx.Headers(headers)
            outgoing["Host"] = original.host
            outgoing["Accept-Encoding"] = "identity"
            async with httpx.AsyncClient(
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(45, connect=10),
                verify=True,
            ) as client:
                async with client.stream(
                    method,
                    target,
                    headers=outgoing,
                    json=body,
                    extensions={"sni_hostname": original.host},
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise _invalid("X402_REDIRECT_REFUSED")
                    if sum(len(key) + len(value) for key, value in response.headers.raw) > MAX_HEADER_BYTES:
                        raise _invalid("X402_RESPONSE_TOO_LARGE")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise _invalid("X402_ENCODING_REFUSED")
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        content.extend(chunk)
                        if len(content) > MAX_BODY_BYTES:
                            raise _invalid("X402_RESPONSE_TOO_LARGE")
                    # Do not return the original Request, which carries payment authority.
                    return httpx.Response(
                        response.status_code, headers=response.headers, content=bytes(content)
                    )
        except X402Error:
            raise
        except Exception:
            raise _invalid("X402_NETWORK_UNAVAILABLE") from None


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _json(data: bytes | str) -> Any:
    def reject_constant(value):
        raise ValueError

    try:
        return json.loads(data, object_pairs_hook=_unique_pairs, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid() from None


def _decode_header(response: httpx.Response, name: str) -> dict:
    try:
        values = response.headers.get_list(name)
        if len(values) != 1 or not 0 < len(values[0]) <= MAX_PAYMENT_HEADER_BYTES:
            raise ValueError
        raw = base64.b64decode(values[0], validate=True)
        if len(raw) > MAX_CHALLENGE_BYTES:
            raise ValueError
        result = _json(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, binascii.Error, UnicodeError):
        raise _invalid() from None


def _validate_action(action: dict) -> None:
    try:
        validate_public_https_url(action["url"])
        requirement, resource = action["payment_requirements"], action["resource"]
        amount, ceiling, timeout = (
            action["amount_atomic"],
            action["max_total_minor"],
            action["max_timeout_seconds"],
        )
        if (
            action["type"] != "x402.pay_request"
            or action["method"] != "GET"
            or action["scheme"] != "exact"
            or action["network"] != BASE_SEPOLIA_NETWORK
            or not isinstance(action["asset"], str)
            or action["asset"].lower() != BASE_SEPOLIA_USDC.lower()
            or not isinstance(action["pay_to"], str)
            or not ADDRESS_RE.fullmatch(action["pay_to"])
            or int(action["pay_to"], 16) == 0
            or not isinstance(amount, str)
            or not ATOM_RE.fullmatch(amount)
            or int(amount) >= 2**256
            or type(ceiling) is not int
            or ceiling <= 0
            or int(amount) > ceiling * 10_000
            or action["currency"] != "USD"
            or type(timeout) is not int
            or not 1 <= timeout <= 300
            or not isinstance(requirement, dict)
            or not isinstance(resource, dict)
            or resource.get("url") != action["url"]
        ):
            raise ValueError
        expected = {
            "scheme": action["scheme"],
            "network": action["network"],
            "asset": action["asset"],
            "payTo": action["pay_to"],
            "amount": amount,
            "maxTimeoutSeconds": timeout,
        }
        if any(
            type(requirement.get(key)) is not type(value) or requirement.get(key) != value
            for key, value in expected.items()
        ):
            raise ValueError
        extra = requirement.get("extra", {})
        if (
            not isinstance(extra, dict)
            or extra.get("assetTransferMethod", "eip3009") != "eip3009"
            or extra.get("name", "USDC") != "USDC"
            or extra.get("version", "2") != "2"
        ):
            raise ValueError
        if (
            len(json.dumps({"requirement": requirement, "resource": resource}, allow_nan=False).encode())
            > MAX_CHALLENGE_BYTES
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise _invalid("X402_INVALID_ACTION") from None


def _load_signer(path: str):
    """Read only a regular, current-user-owned key file with no group/other access."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077
                or metadata.st_size > 80
            ):
                raise ValueError
            key = stream.read(81).strip().decode("ascii")
        if not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", key):
            raise ValueError
        from eth_account import Account
        from x402.mechanisms.evm import EthAccountSigner

        return EthAccountSigner(Account.from_key(key))
    except Exception:
        raise _invalid("X402_KEY_UNAVAILABLE") from None


def _validate_authorization(payload: dict, action: dict, payer: str) -> str:
    try:
        inner = payload["payload"]
        authorization = inner["authorization"]
        now = int(time.time())
        if (
            payload["x402Version"] != 2
            or set(inner) != {"authorization", "signature"}
            or not ADDRESS_RE.fullmatch(payer)
            or authorization["from"].lower() != payer.lower()
            or authorization["to"].lower() != action["pay_to"].lower()
            or authorization["value"] != action["amount_atomic"]
            or authorization["validAfter"] != "0"
            or not isinstance(authorization["validBefore"], str)
            or not re.fullmatch(r"[1-9][0-9]{0,11}", authorization["validBefore"])
            or not now < int(authorization["validBefore"]) <= now + action["max_timeout_seconds"] + 2
            or not HASH_RE.fullmatch(authorization["nonce"])
            or not re.fullmatch(r"0x[0-9a-fA-F]{130}", inner["signature"])
        ):
            raise ValueError
        return authorization["nonce"].lower()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise _invalid("X402_INVALID_AUTHORIZATION") from None


def _hex_quantity(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,15})", value):
        raise _invalid("X402_INVALID_RECEIPT")
    return int(value, 16)


def verify_receipt(receipt: Any, transaction: str, action: dict, payer: str, nonce: str) -> int:
    """Bind mined token logs to this authorization, not an earlier equal-value payment."""
    try:
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") != "0x1"
            or receipt.get("transactionHash", "").lower() != transaction.lower()
            or not HASH_RE.fullmatch(receipt.get("blockHash", ""))
            or not isinstance(receipt.get("logs"), list)
            or len(receipt["logs"]) > 512
        ):
            raise ValueError
        block_number = _hex_quantity(receipt.get("blockNumber"))
        if block_number <= 0:
            raise ValueError
        payer_topic = "0x" + "0" * 24 + payer[2:].lower()
        payee_topic = "0x" + "0" * 24 + action["pay_to"][2:].lower()
        transfer_found = authorization_found = False
        for log in receipt["logs"]:
            if not isinstance(log, dict) or str(log.get("address", "")).lower() != BASE_SEPOLIA_USDC.lower():
                continue
            if (
                log.get("removed") is not False
                or str(log.get("transactionHash", "")).lower() != transaction.lower()
                or str(log.get("blockHash", "")).lower() != receipt["blockHash"].lower()
                or log.get("blockNumber") != receipt["blockNumber"]
            ):
                raise ValueError
            topics = log.get("topics")
            if not isinstance(topics, list) or not all(isinstance(value, str) for value in topics):
                raise ValueError
            topics = [value.lower() for value in topics]
            data = log.get("data")
            if topics == [TRANSFER_TOPIC, payer_topic, payee_topic]:
                if not isinstance(data, str) or not HASH_RE.fullmatch(data):
                    raise ValueError
                transfer_found |= int(data, 16) == int(action["amount_atomic"])
            if topics == [AUTHORIZATION_USED_TOPIC, payer_topic, nonce.lower()] and data == "0x":
                authorization_found = True
        if not transfer_found or not authorization_found:
            raise ValueError
        return block_number
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _invalid("X402_UNVERIFIED_SETTLEMENT") from None


class X402Client:
    def __init__(
        self,
        private_key_file: str,
        rpc_url: str = "https://sepolia.base.org",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = _resolve,
        receipt_timeout_seconds: float = RECEIPT_TIMEOUT_SECONDS,
        receipt_poll_interval_seconds: float = 1.0,
    ):
        if (
            type(receipt_timeout_seconds) not in (int, float)
            or not math.isfinite(receipt_timeout_seconds)
            or not 0 < receipt_timeout_seconds <= RECEIPT_TIMEOUT_SECONDS
            or type(receipt_poll_interval_seconds) not in (int, float)
            or not math.isfinite(receipt_poll_interval_seconds)
            or not 0 < receipt_poll_interval_seconds <= receipt_timeout_seconds
        ):
            raise ValueError("Receipt polling requires a positive interval and a timeout of at most 12 seconds.")
        self._receipt_timeout_seconds = float(receipt_timeout_seconds)
        self._receipt_poll_interval_seconds = float(receipt_poll_interval_seconds)
        self._private_key_file = private_key_file
        self._rpc_url = validate_public_https_url(rpc_url)
        self._http = PublicHTTPSClient(transport=transport, resolver=resolver)

    def __repr__(self) -> str:
        return "X402Client()"

    async def discover(self, url: str) -> dict:
        response = await self._http.request("GET", url)
        if response.status_code != 402:
            raise _invalid("X402_PAYMENT_REQUIRED_EXPECTED")
        challenge = _decode_header(response, "PAYMENT-REQUIRED")
        if (
            type(challenge.get("x402Version")) is not int
            or challenge["x402Version"] != 2
            or not isinstance(challenge.get("accepts"), list)
            or not 1 <= len(challenge["accepts"]) <= 16
        ):
            raise _invalid()
        return challenge

    async def _rpc(self, method: str, parameters: list) -> Any:
        response = await self._http.request(
            "POST", self._rpc_url, body={"jsonrpc": "2.0", "id": 1, "method": method, "params": parameters}
        )
        if response.status_code != 200:
            raise _invalid("X402_RPC_UNAVAILABLE")
        data = _json(response.content)
        if (
            not isinstance(data, dict)
            or data.get("jsonrpc") != "2.0"
            or type(data.get("id")) is not int
            or data["id"] != 1
            or "error" in data
            or "result" not in data
        ):
            raise _invalid("X402_RPC_UNAVAILABLE")
        return data["result"]

    async def _wait_for_receipt(self, transaction: str, authorization_expires_at: int) -> Any:
        """Poll only an absent receipt; never repeat signing or the paid HTTP request."""
        remaining = min(self._receipt_timeout_seconds, authorization_expires_at - time.time())
        if remaining <= 0:
            raise _invalid("X402_SETTLEMENT_TIMEOUT")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + remaining
        try:
            async with asyncio.timeout_at(deadline):
                while True:
                    if loop.time() >= deadline:
                        raise TimeoutError
                    receipt = await self._rpc("eth_getTransactionReceipt", [transaction])
                    if loop.time() >= deadline:
                        raise TimeoutError
                    if receipt is not None:
                        return receipt
                    await asyncio.sleep(min(self._receipt_poll_interval_seconds, deadline - loop.time()))
        except TimeoutError:
            raise _invalid("X402_SETTLEMENT_TIMEOUT") from None

    async def _check_chain(self) -> None:
        if _hex_quantity(await self._rpc("eth_chainId", [])) != 84532:
            raise _invalid("X402_WRONG_CHAIN")

    async def _create_payload(self, action: dict) -> tuple[dict, str]:
        try:
            from x402 import x402Client
            from x402.mechanisms.evm.exact import ExactEvmScheme
            from x402.schemas import PaymentRequired

            signer = _load_signer(self._private_key_file)
            client = x402Client()
            client.register(BASE_SEPOLIA_NETWORK, ExactEvmScheme(signer))
            ceiling = action["max_total_minor"]
            client.set_spend_controls(
                {
                    "max_amount_per_payment": f"${ceiling // 100}.{ceiling % 100:02d}",
                    "allowed_assets": [
                        {
                            "network": BASE_SEPOLIA_NETWORK,
                            "asset": BASE_SEPOLIA_USDC,
                            "max_amount_per_payment": str(ceiling * 10_000),
                        }
                    ],
                }
            )
            sdk_requirement = copy.deepcopy(action["payment_requirements"])
            # The SDK otherwise defaults an explicitly named token without a
            # version to EIP-712 version 1. This exact known contract uses 2.
            sdk_requirement.setdefault("extra", {}).update(name="USDC", version="2")
            required = PaymentRequired.model_validate(
                {
                    "x402Version": 2,
                    "accepts": [sdk_requirement],
                    "resource": copy.deepcopy(action["resource"]),
                }
            )
            payload = await client.create_payment_payload(required)
            decoded = payload.model_dump(by_alias=True, exclude_none=True)
            # SDK models intentionally ignore unknown fields. The approved original
            # requirement and resource must still be echoed byte-for-value in JSON.
            decoded["accepted"] = copy.deepcopy(action["payment_requirements"])
            decoded["resource"] = copy.deepcopy(action["resource"])
            _validate_authorization(decoded, action, signer.address)
            return decoded, signer.address
        except X402Error:
            raise
        except ImportError:
            raise _invalid("X402_SDK_UNAVAILABLE") from None
        except Exception:
            raise _invalid("X402_SIGNING_UNAVAILABLE") from None

    async def pay(self, action: dict) -> dict:
        """One signed GET at most. Every failure retains authority as uncertain upstream."""
        try:
            action = copy.deepcopy(action)
            _validate_action(action)
            await self._check_chain()  # Before loading a key or signing anything.
            payload, payer = await self._create_payload(action)
            nonce = _validate_authorization(payload, action, payer)
            signature = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode("ascii")
            if len(signature) > MAX_PAYMENT_HEADER_BYTES:
                raise _invalid("X402_AUTHORIZATION_TOO_LARGE")
            response = await self._http.request(
                "GET", action["url"], headers={"PAYMENT-SIGNATURE": signature}
            )
            # A second 402, redirect, exception or error must never trigger re-signing.
            if not 200 <= response.status_code < 300:
                raise _invalid("X402_PAYMENT_UNCERTAIN")
            settlement = _decode_header(response, "PAYMENT-RESPONSE")
            transaction = settlement.get("transaction")
            if (
                settlement.get("success") is not True
                or settlement.get("network") != BASE_SEPOLIA_NETWORK
                or not isinstance(transaction, str)
                or not HASH_RE.fullmatch(transaction)
                or (
                    settlement.get("payer") is not None
                    and (
                        not isinstance(settlement["payer"], str)
                        or settlement["payer"].lower() != payer.lower()
                    )
                )
                or ("amount" in settlement and settlement["amount"] != action["amount_atomic"])
            ):
                raise _invalid("X402_UNVERIFIED_SETTLEMENT")
            await self._check_chain()
            receipt = await self._wait_for_receipt(
                transaction, int(payload["payload"]["authorization"]["validBefore"])
            )
            block = verify_receipt(receipt, transaction, action, payer, nonce)
            text = response.content.decode("utf-8")
            if signature in text or payload["payload"]["signature"].lower() in text.lower():
                raise _invalid("X402_UNSAFE_RESULT")
            content_type = response.headers.get("content-type", "text/plain").split(";", 1)[0].lower()
            if len(content_type) > 128 or not re.fullmatch(
                r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", content_type
            ):
                raise _invalid("X402_INVALID_RESULT")
            result = (
                _json(text) if content_type == "application/json" or content_type.endswith("+json") else text
            )
            serialized = json.dumps(result, ensure_ascii=False)
            if signature in serialized or payload["payload"]["signature"].lower() in serialized.lower():
                raise _invalid("X402_UNSAFE_RESULT")
            return {
                "status": "SUCCEEDED",
                "result": {"content_type": content_type, "body": result},
                "settlement": {
                    "network": BASE_SEPOLIA_NETWORK,
                    "transaction": transaction,
                    "payer": payer,
                    "asset": action["asset"],
                    "pay_to": action["pay_to"],
                    "amount_atomic": action["amount_atomic"],
                    "verified": True,
                    "authorization_verified": True,
                    "block_number": block,
                },
            }
        except X402Error as error:
            return {"status": "UNCERTAIN", "reason": error.code, "result": None, "settlement": None}
        except Exception:
            return {
                "status": "UNCERTAIN",
                "reason": "X402_PAYMENT_UNCERTAIN",
                "result": None,
                "settlement": None,
            }

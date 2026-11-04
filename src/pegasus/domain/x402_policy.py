"""Exact, opt-in testnet API-payment rules without transport or wallet code."""

from dataclasses import dataclass, field
import ipaddress
import json
import re
from urllib.parse import urlsplit

from .exceptions import Denied

BASE_SEPOLIA_NETWORK = "eip155:84532"
BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
X402_ACTION = "x402.pay_request"
ATOMS_PER_CENT = 10_000
MAX_ATOMIC_AMOUNT = 2**256 - 1
MAX_TIMEOUT_SECONDS = 300
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")
TRANSACTION_RE = re.compile(r"0x[0-9a-fA-F]{64}\Z")
DNS_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


@dataclass(frozen=True)
class X402Policy:
    enabled: bool = False
    allowed_origins: frozenset[str] = field(default_factory=frozenset)
    allowed_payees: frozenset[str] = field(default_factory=frozenset)
    max_purchase_minor: int = 500
    max_daily_minor: int = 1000
    quote_ttl_seconds: int = 300
    grant_ttl_seconds: int = 90


def _origin(url: str, *, origin_only: bool = False) -> str:
    if (
        not isinstance(url, str)
        or not 1 <= len(url) <= 2048
        or not url.isascii()
        or re.search(r"[\x00-\x20\x7f\\#]", url)
    ):
        raise Denied("X402_URL_DENIED", "Select an allowlisted public HTTPS API URL.")
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise Denied("X402_URL_DENIED", "Select an allowlisted public HTTPS API URL.") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or (origin_only and (parsed.path not in ("", "/") or parsed.query))
    ):
        raise Denied("X402_URL_DENIED", "Select an allowlisted public HTTPS API URL.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise Denied("X402_URL_DENIED", "An allowlisted public DNS hostname is required.")
    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or any(not DNS_LABEL_RE.fullmatch(label) for label in labels)
        or not re.fullmatch(r"[a-z]{2,63}", labels[-1])
        or labels[-1] in {"localhost", "local", "internal", "lan", "home", "test", "invalid", "example"}
        or host.endswith((".localhost", ".local", ".internal", ".localdomain"))
    ):
        raise Denied("X402_URL_DENIED", "An allowlisted public DNS hostname is required.")
    return "https://" + host


def _json_copy(value, *, max_bytes: int = 16384):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > max_bytes:
            raise ValueError()
        return json.loads(encoded)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise Denied("X402_CHALLENGE_INVALID", "Payment terms must be bounded JSON data.") from None


def validate_request(request: dict, policy: X402Policy) -> str:
    """Reject unapproved destinations and ceilings before unpaid discovery."""
    if not policy.enabled:
        raise Denied("X402_DISABLED", "External API payments are not configured.")
    if not isinstance(request, dict) or set(request) != {"url", "max_total_minor"}:
        raise Denied("INVALID_INPUT", "API payments accept only a GET URL and USD-cent ceiling.")
    maximum = request["max_total_minor"]
    if (
        type(maximum) is not int
        or maximum <= 0
        or type(policy.max_purchase_minor) is not int
        or maximum > policy.max_purchase_minor
    ):
        raise Denied("PURCHASE_CAP", "The approved maximum must fit the per-purchase USD cap.")
    origin = _origin(request["url"])
    allowed = {_origin(value, origin_only=True) for value in policy.allowed_origins}
    if origin not in allowed:
        raise Denied("X402_ORIGIN_DENIED", "API origin is outside the local allowlist.")
    return request["url"]


def _validate_requirement(requirement: dict, maximum: int, policy: X402Policy) -> tuple[str, int]:
    if requirement.get("scheme") != "exact":
        raise Denied("X402_SCHEME_DENIED", "Only exact API payments are supported.")
    if requirement.get("network") != BASE_SEPOLIA_NETWORK:
        raise Denied("X402_NETWORK_DENIED", "Only Base Sepolia testnet payments are allowed.")
    extra = requirement.get("extra", {})
    if not isinstance(extra, dict) or extra.get("assetTransferMethod", "eip3009") != "eip3009":
        raise Denied("X402_TRANSFER_METHOD_DENIED", "Only EIP-3009 authorizations are supported.")
    if extra.get("name", "USDC") != "USDC" or extra.get("version", "2") != "2":
        raise Denied("X402_TOKEN_DOMAIN_DENIED", "USDC signing-domain metadata could not be verified.")
    asset = requirement.get("asset")
    if not isinstance(asset, str) or asset.lower() != BASE_SEPOLIA_USDC.lower():
        raise Denied("X402_ASSET_DENIED", "Only the configured Base Sepolia USDC token is allowed.")
    payee = requirement.get("payTo")
    if (
        not isinstance(payee, str)
        or not ADDRESS_RE.fullmatch(payee)
        or int(payee[2:], 16) == 0
        or payee.lower() not in {value.lower() for value in policy.allowed_payees if isinstance(value, str)}
    ):
        raise Denied("X402_PAYEE_DENIED", "Payment recipient is outside the local allowlist.")
    amount = requirement.get("amount")
    if (
        not isinstance(amount, str)
        or not re.fullmatch(r"[1-9][0-9]{0,77}", amount)
        or int(amount) > MAX_ATOMIC_AMOUNT
    ):
        raise Denied("X402_INVALID_AMOUNT", "USDC atoms must be a bounded positive integer string.")
    if int(amount) > maximum * ATOMS_PER_CENT:
        raise Denied("PURCHASE_CAP", "The exact payment exceeds the approved USD ceiling.")
    timeout = requirement.get("maxTimeoutSeconds")
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise Denied("X402_TIMEOUT_DENIED", "Payment authorizations must expire within five minutes.")
    return amount, timeout


def validate_quote(request: dict, challenge: dict, policy: X402Policy) -> dict:
    """Select one supported requirement and bind all its original metadata."""
    url = validate_request(request, policy)
    if not isinstance(challenge, dict) or type(challenge.get("x402Version")) is not int:
        raise Denied("X402_CHALLENGE_INVALID", "A valid x402 v2 payment challenge is required.")
    if challenge["x402Version"] != 2:
        raise Denied("X402_VERSION_DENIED", "Only x402 version 2 is supported.")
    resource = challenge.get("resource")
    if not isinstance(resource, dict) or resource.get("url") != url:
        raise Denied("X402_RESOURCE_MISMATCH", "Payment resource must match the exact approved URL.")
    resource = _json_copy(resource)
    requirements = challenge.get("accepts")
    if (
        not isinstance(requirements, list)
        or not 1 <= len(requirements) <= 16
        or any(not isinstance(requirement, dict) for requirement in requirements)
    ):
        raise Denied("X402_CHALLENGE_INVALID", "A bounded list of payment requirements is required.")
    first_error = None
    for original in requirements:
        try:
            requirement = _json_copy(original)
            amount, timeout = _validate_requirement(requirement, request["max_total_minor"], policy)
        except Denied as error:
            if first_error is None:
                first_error = error
            continue
        return {
            "type": X402_ACTION,
            "method": "GET",
            "url": url,
            "scheme": "exact",
            "network": BASE_SEPOLIA_NETWORK,
            "asset": requirement["asset"],
            "pay_to": requirement["payTo"],
            "amount_atomic": amount,
            "total_minor": (int(amount) + ATOMS_PER_CENT - 1) // ATOMS_PER_CENT,
            "max_total_minor": request["max_total_minor"],
            "currency": "USD",
            "max_timeout_seconds": timeout,
            "payment_requirements": requirement,
            "resource": resource,
        }
    raise first_error


def settlement_verified(settlement: dict, action: dict) -> bool:
    """Require the trusted adapter's complete, independently checked receipt tuple."""
    if not isinstance(settlement, dict):
        return False
    asset, payee = settlement.get("asset"), settlement.get("pay_to")
    payer, transaction = settlement.get("payer"), settlement.get("transaction")
    return (
        settlement.get("verified") is True
        and settlement.get("authorization_verified") is True
        and settlement.get("network") == BASE_SEPOLIA_NETWORK
        and isinstance(asset, str)
        and asset.lower() == action["asset"].lower() == BASE_SEPOLIA_USDC.lower()
        and isinstance(payee, str)
        and payee.lower() == action["pay_to"].lower()
        and settlement.get("amount_atomic") == action["amount_atomic"]
        and isinstance(payer, str)
        and bool(ADDRESS_RE.fullmatch(payer))
        and int(payer[2:], 16) != 0
        and isinstance(transaction, str)
        and bool(TRANSACTION_RE.fullmatch(transaction))
        and type(settlement.get("block_number")) is int
        and settlement["block_number"] > 0
    )

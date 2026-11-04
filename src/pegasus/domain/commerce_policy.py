from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from .exceptions import Denied


@dataclass(frozen=True)
class CommercePolicy:
    max_purchase_minor: int
    max_daily_minor: int
    allowed_products: frozenset[str]
    allowed_countries: frozenset[str]
    allowed_emails: frozenset[str]
    allowed_recipients: frozenset[str]
    quote_ttl_seconds: int
    grant_ttl_seconds: int


MANUAL_METHODS = frozenset(
    {
        "bitcoin",
        "lightning",
        "ark",
        "ethereum",
        "eth_base",
        "eth_arbitrum",
        "solana",
        "litecoin",
        "dogecoin",
        "dash",
        "ton",
        "usdc_base",
        "usdc_polygon",
        "usdc_arbitrum",
        "usdc_solana",
        "usdc_erc20",
        "usdt_erc20",
        "usdt_trc20",
        "usdt_polygon",
        "usdt_arbitrum",
        "usdt_solana",
    }
)


def minor_units(value, currency):
    # This MVP has one accounting currency; there is no implicit FX conversion.
    if currency != "USD":
        raise Denied("CURRENCY_UNSUPPORTED", "Only verified USD quotes are supported.")
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
            raise ValueError()
        return int(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise Denied("INVALID_PRICE", "Provider price must be a positive exact USD cent amount.") from None


ACCOUNT_REFERENCE_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def validate_receipt(request, details, settings):
    mode = request.get("receipt_mode", "email")
    if not isinstance(mode, str) or mode not in {"email", "provider_account"}:
        raise Denied("RECEIPT_MODE_DENIED", "Receipt mode must be email or the connected provider account.")
    destination = details.get("receipt_destination", {"mode": "email"})
    if (
        not isinstance(destination, dict)
        or not isinstance(destination.get("mode"), str)
        or destination["mode"] not in {"email", "provider_account"}
    ):
        raise Denied("RECEIPT_UNVERIFIED", "Provider receipt destination could not be verified.")
    if mode != destination["mode"]:
        raise Denied("RECEIPT_MODE_MISMATCH", "Provider receipt mode changed. Create and approve a fresh intent.")
    email = request.get("email", "")
    reference = request.get("receipt_account_reference")
    if mode == "email":
        if reference is not None:
            raise Denied("RECEIPT_ACCOUNT_UNEXPECTED", "An email receipt cannot select a provider account.")
        if not email or email not in settings.allowed_emails:
            raise Denied("EMAIL_DENIED", "Receipt email is outside the local allowlist.")
        return {}
    trusted_reference = destination.get("account_reference")
    if not isinstance(trusted_reference, str) or not ACCOUNT_REFERENCE_RE.fullmatch(trusted_reference):
        raise Denied("RECEIPT_UNVERIFIED", "Provider receipt account could not be verified.")
    if not isinstance(reference, str) or reference != trusted_reference:
        raise Denied(
            "RECEIPT_ACCOUNT_MISMATCH", "Connected receipt account changed. Create and approve a fresh intent."
        )
    if email != "":
        raise Denied("RECEIPT_EMAIL_UNEXPECTED", "Connected-account receipts require an empty email field.")
    return {"receipt_mode": mode, "receipt_account_reference": reference}


def validate_quote(request, details, settings):
    if request["product_id"] not in settings.allowed_products:
        raise Denied("PRODUCT_DENIED", "Product is outside the local allowlist.")
    if details.get("product_id") != request["product_id"]:
        raise Denied("PRODUCT_MISMATCH", "Provider returned a different product.")
    country = request["country"]
    if country not in settings.allowed_countries or country not in details.get("countries", []):
        raise Denied("COUNTRY_DENIED", "Product country could not be verified against policy.")
    if details.get("in_stock") is not True:
        raise Denied("OUT_OF_STOCK", "Product is unavailable.")
    method = request["payment_method"]
    if method not in MANUAL_METHODS or method not in details.get("payment_methods", []):
        raise Denied("PAYMENT_METHOD_DENIED", "Select a provider-supported manual crypto payment method.")
    matches = [p for p in details.get("packages", []) if p.get("package_value") == request["package_value"]]
    if len(matches) != 1:
        raise Denied("PACKAGE_DENIED", "Exact denomination was not found in the current provider catalog.")
    price = matches[0]
    currency = price.get("payment_currency")
    total = minor_units(price.get("payment_price"), currency)
    maximum = request["max_total_minor"]
    if total > maximum or maximum > settings.max_purchase_minor:
        raise Denied("PURCHASE_CAP", "Quoted price or approved maximum exceeds the spend cap.")
    receipt = validate_receipt(request, details, settings)
    kind = details.get("recipient_type")
    recipient = request.get("recipient", "")
    if kind not in {"none", "phone_number", "account", "email", "username"}:
        raise Denied("RECIPIENT_UNVERIFIED", "Provider recipient requirements could not be verified.")
    if kind == "none" and recipient:
        raise Denied("RECIPIENT_UNEXPECTED", "This product does not accept a recipient field.")
    if kind != "none" and (not recipient or recipient not in settings.allowed_recipients):
        raise Denied("RECIPIENT_DENIED", "Recipient is outside the local allowlist.")
    if kind == "phone_number" and (not recipient.isascii() or not recipient.isdigit()):
        raise Denied("RECIPIENT_FORMAT", "MCP phone recipients use international digits without '+'.")
    return {
        "schema_version": 1,
        "product_id": request["product_id"],
        "package_value": request["package_value"],
        "quantity": 1,
        "country": country,
        "recipient_type": kind,
        "recipient": recipient,
        "email": request.get("email", ""),
        "payment_method": method,
        "currency": currency,
        "total_minor": total,
        "max_total_minor": maximum,
        **receipt,
    }


def invoice_verified(invoice, action):
    total = invoice.get("total_minor")
    expected = {
        "items": [
            {
                "product_id": action["product_id"],
                "package_value": action["package_value"],
                "quantity": action["quantity"],
                "recipient": action["recipient"],
            }
        ],
        "payment_method": action["payment_method"],
    }
    receipt_mode = action.get("receipt_mode", "email")
    if receipt_mode == "provider_account":
        reference = action.get("receipt_account_reference")
        if (
            action["email"] != ""
            or not isinstance(reference, str)
            or not ACCOUNT_REFERENCE_RE.fullmatch(reference)
        ):
            return False
        expected["receipt_destination"] = {"mode": "provider_account", "account_reference": reference}
    elif receipt_mode == "email" and action.get("receipt_account_reference") is None:
        expected["email"] = action["email"]
    else:
        return False
    return (
        type(total) is int
        and 0 < total <= action["max_total_minor"]
        and invoice.get("currency") == action["currency"]
        and invoice.get("verified_terms") == expected
    )


def invoice_status(invoice):
    status = invoice.get("status", "unknown")
    orders = invoice.get("orders", [])
    if status in {"blocked", "denied", "payment_error", "failed"}:
        return "FAILED"
    if status in {"expired", "cancelled"}:
        return "EXPIRED"
    if any(order.get("status") in {"failed", "refunded"} for order in orders):
        return "FAILED"
    if orders and all(order.get("status") == "delivered" for order in orders):
        return "DELIVERED" if status in {"payment_confirmed", "pending", "complete"} else "BLOCKED"
    return {
        "unpaid": "UNPAID",
        "payment_detected": "PAYMENT_DETECTED",
        "payment_confirmed": "PAYMENT_CONFIRMED",
        "pending": "PENDING_DELIVERY",
        "complete": "PENDING_DELIVERY",
    }.get(status, "BLOCKED")

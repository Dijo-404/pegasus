"""Small, fail-closed adapter for Bitrefill's authenticated MCP surface.

The provider is authoritative for catalog and invoice facts, never for policy.
Only this module sees the bearer credential. No response descriptions, payment
secrets, redemption codes, or provider-generated instructions leave the adapter.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx
import jsonschema
import toon_format
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from pegasus.domain.exceptions import IntegrationError

ENDPOINT = "https://api.bitrefill.com/mcp"
TOOLS = frozenset({"search-products", "get-product-details", "buy-products", "get-invoice-by-id"})
# This MVP supports manual crypto checkout only. Neither balance, cashback,
# saved cards, arbitrary URLs nor payment signing can be selected by a model.
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
        "usdt_ton",
        "usdc_base",
        "usdc_erc20",
        "usdt_erc20",
        "usdc_polygon",
        "usdt_polygon",
        "usdc_arbitrum",
        "usdt_arbitrum",
        "usdc_solana",
        "usdt_solana",
        "usdc_bsc",
        "usdt_bsc",
        "usdt_trc20",
    }
)
INVOICE_STATUSES = frozenset(
    {
        "unpaid",
        "payment_detected",
        "payment_confirmed",
        "pending",
        "complete",
        "blocked",
        "denied",
        "payment_error",
        "expired",
    }
)
ORDER_STATUSES = frozenset(
    {
        "created",
        "payment_detected",
        "processing",
        "delivered",
        "failed",
        "refunded",
    }
)


class ProviderError(IntegrationError):
    """A safe error; never include a provider payload or credential in message."""


def _bad(message: str = "Provider response could not be verified.") -> ProviderError:
    return ProviderError("PROVIDER_INVALID_RESPONSE", message)


def _unwrap(data: Any) -> Any:
    # The documented buy-products envelope is {response, agent_instructions}.
    # The latter is untrusted prose and is deliberately never returned.
    if isinstance(data, dict) and isinstance(data.get("response"), (dict, list)):
        return data["response"]
    if isinstance(data, dict) and isinstance(data.get("data"), (dict, list)):
        return data["data"]
    return data


def _decode_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        raise ProviderError(
            "PROVIDER_REJECTED", "Bitrefill rejected the request; no automatic retry was made."
        )
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, (dict, list)):
        return _unwrap(structured)
    blocks = getattr(result, "content", [])
    texts = [block.text for block in blocks if getattr(block, "type", None) == "text"]
    if len(texts) != 1 or len(texts[0]) > 2_000_000:
        raise _bad()
    text = texts[0]
    try:
        parsed = json.loads(text, parse_float=Decimal)
    except (json.JSONDecodeError, ValueError):
        try:
            parsed = toon_format.loads(text, parse_float=Decimal)
        except (ValueError, TypeError, RecursionError):
            raise _bad() from None
    if not isinstance(parsed, (dict, list)):
        raise _bad()
    return _unwrap(parsed)


def _text(value: Any, *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _bad()
    return value


def _countries(data: dict) -> list[str]:
    values = data.get("countries")
    if values is None and data.get("country_code") is not None:
        values = [data["country_code"]]
    if not isinstance(values, list) or not values:
        raise _bad("Provider did not supply a verifiable product region.")
    if any(not isinstance(c, str) or len(c) != 2 or not c.isalpha() or c != c.upper() for c in values):
        raise _bad()
    return sorted(set(values))


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise _bad("Provider did not supply an exact decimal price.")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise _bad() from None
    if not amount.is_finite() or amount <= 0:
        raise _bad()
    return amount


def _payment_link(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4096:
        raise _bad()
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in {"www.bitrefill.com", "bitrefill.com"}
            and not parsed.username
            and not parsed.password
            and parsed.port in {None, 443}
        )
    except ValueError:
        valid = False
    if not valid:
        raise _bad("Provider returned an untrusted payment destination.")
    return value


def _invoice_terms(data: dict) -> dict | None:
    """Extract only terms actually returned by the provider.

    The partner guide documents ``response.cart_items``; the call schema says
    repeated cart entries mean multiple units. A single entry without an
    explicit quantity therefore denotes one unit. Missing receipt email,
    payment method or denominations cannot be filled from our original request.
    The caller must withhold the payment link when this proof is unavailable.
    """
    cart = data.get("cart_items")
    email = data.get("email")
    method = data.get("payment_method")
    if method is None and isinstance(data.get("payment"), dict):
        method = data["payment"].get("method")
    if not isinstance(cart, list) or not cart or not isinstance(email, str) or not isinstance(method, str):
        return None
    items = []
    for entry in cart:
        if not isinstance(entry, dict):
            return None
        product_id = entry.get("product_id")
        package_value = entry.get("package_value", entry.get("package_id"))
        recipient = entry.get("refill_input", "")
        quantity = entry.get("quantity", 1)
        if (
            not isinstance(product_id, str)
            or not product_id
            or not isinstance(package_value, str)
            or not package_value
            or not isinstance(recipient, str)
            or type(quantity) is not int
            or quantity <= 0
            or entry.get("gift")
            or entry.get("bill_payment_id")
        ):
            return None
        items.append(
            {
                "product_id": product_id,
                "package_value": package_value,
                "quantity": quantity,
                "recipient": recipient,
            }
        )
    return {"items": items, "email": email, "payment_method": method}


def normalize_invoice(raw: Any, *, expected_id: str | None = None) -> dict:
    data = _unwrap(raw)
    if not isinstance(data, dict):
        raise _bad()
    invoice_id = _text(data.get("invoice_id", data.get("id")))
    if expected_id is not None and invoice_id != expected_id:
        raise _bad("Provider returned a different invoice.")
    status = data.get("invoice_status", data.get("status"))
    if status is not None and status not in INVOICE_STATUSES:
        raise _bad("Provider returned an unknown invoice state.")
    raw_orders = data.get("orders", [])
    if not isinstance(raw_orders, list):
        raise _bad()
    orders = []
    for order in raw_orders:
        if not isinstance(order, dict) or order.get("status") not in ORDER_STATUSES:
            raise _bad("Provider returned an unknown delivery state.")
        orders.append({"id": _text(order.get("id", order.get("order_id"))), "status": order["status"]})
    # A payment_info.amount is a crypto-denominated amount, not a USD quote.
    # Never use the original quote as a substitute for an authoritative total.
    currency, minor = None, None
    candidates = [(data.get("payment_price"), data.get("payment_currency"))]
    candidates.append((data.get("total"), data.get("currency")))
    if isinstance(data.get("payment"), dict):
        candidates.append((data["payment"].get("price"), data["payment"].get("currency")))
    for value, denomination in candidates:
        if (
            value is None
            or not isinstance(denomination, str)
            or denomination not in {"USD", "EUR", "INR", "GBP", "CAD", "AUD", "BRL"}
        ):
            continue
        exact = _decimal(value) * 100
        if exact != exact.to_integral_value():
            raise _bad("Invoice price has unsupported precision.")
        if currency is not None and (currency, minor) != (denomination, int(exact)):
            raise _bad("Provider supplied inconsistent invoice totals.")
        currency, minor = denomination, int(exact)
    result = {
        "invoice_id": invoice_id,
        "status": status or "unknown",
        "orders": orders,
        "payment_link": _payment_link(data.get("payment_link")),
        "total_minor": minor,
        "currency": currency,
        "verified_terms": _invoice_terms(data),
    }
    if data.get("invoice_access_token") is not None:
        result["invoice_access_token"] = _text(data["invoice_access_token"], maximum=4096)
    return result


class BitrefillClient:
    def __init__(self, api_key: str):
        self._api_key = api_key

    @asynccontextmanager
    async def _session(self):
        if not self._api_key:
            raise ProviderError(
                "BITREFILL_NOT_CONFIGURED",
                "Set BITREFILL_API_KEY in the trusted backend to enable live commerce.",
            )
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(45, connect=10),
            trust_env=True,
            follow_redirects=False,
        ) as http_client:
            # The upstream is stateless: GET/DELETE return 405. Do not attempt
            # session termination against a server that has no sessions.
            async with streamable_http_client(
                ENDPOINT, http_client=http_client, terminate_on_close=False
            ) as streams:
                async with ClientSession(
                    streams[0], streams[1], read_timeout_seconds=timedelta(seconds=50)
                ) as session:
                    await session.initialize()
                    yield session

    @staticmethod
    async def _schemas(session: Any) -> dict[str, dict]:
        schemas = {}
        cursor = None
        for _ in range(10):
            page = await session.list_tools(cursor=cursor)
            for tool in page.tools:
                if tool.name in TOOLS:
                    schemas[tool.name] = tool.inputSchema
            cursor = page.nextCursor
            if not cursor:
                return schemas
        raise ProviderError("PROVIDER_SCHEMA", "Bitrefill's tool list exceeded the supported size.")

    @staticmethod
    def _args(schema: dict, args: dict) -> dict:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        result = {key: value for key, value in args.items() if key in properties}
        if any(key not in result for key in required):
            raise ProviderError(
                "PROVIDER_SCHEMA", "Bitrefill requires fields this minimal adapter does not support."
            )
        try:
            jsonschema.validate(result, schema, format_checker=jsonschema.FormatChecker())
        except (jsonschema.ValidationError, jsonschema.SchemaError):
            raise ProviderError(
                "PROVIDER_SCHEMA", "Request does not match Bitrefill's live tool schema."
            ) from None
        return result

    async def _call(self, name: str, args: dict | Any) -> Any:
        if name not in TOOLS:
            raise ProviderError("TOOL_DENIED", "This provider tool is not allowed.")
        # One write attempt only. Read failures may retry after bounded backoff.
        attempts = 1 if name == "buy-products" else 3
        for attempt in range(attempts):
            try:
                async with self._session() as session:
                    schemas = await self._schemas(session)
                    if name not in schemas:
                        raise ProviderError(
                            "PROVIDER_SCHEMA", "Required Bitrefill tool is unavailable for this credential."
                        )
                    arguments = args(schemas[name]) if callable(args) else args
                    validated = self._args(schemas[name], arguments)
                    result = await session.call_tool(name, validated)
                    return _decode_result(result)
            except ProviderError:
                raise
            except Exception as exc:
                status = _http_status(exc)
                if status in {401, 403}:
                    raise ProviderError(
                        "PROVIDER_AUTH", "Bitrefill authentication failed. Verify the backend credential."
                    ) from None
                if name == "buy-products":
                    raise ProviderError(
                        "PROVIDER_UNCERTAIN",
                        "Invoice creation was interrupted. Reconcile before any further purchase attempt.",
                    ) from None
                retryable = status == 429 or status is None or (status is not None and status >= 500)
                if attempt + 1 == attempts or not retryable:
                    code = "PROVIDER_RATE_LIMIT" if status == 429 else "PROVIDER_UNAVAILABLE"
                    raise ProviderError(code, "Bitrefill is unavailable. Retry this read later.") from None
                await asyncio.sleep(2**attempt)
        raise ProviderError("PROVIDER_UNAVAILABLE", "Bitrefill is unavailable.")

    async def check(self) -> dict:
        # A read-only search validates authentication, protocol, schema and decode.
        await self.search("airtel", "IN", "Pegasus read-only connection check")
        return {"provider": "bitrefill", "connected": True, "transport": "mcp"}

    async def search(self, query: str, country: str, intent: str) -> list[dict]:
        raw = await self._call(
            "search-products",
            {
                "query": query,
                "country": country,
                "intent": intent,
                "in_stock": True,
                "per_page": 25,
            },
        )
        products = raw.get("products") if isinstance(raw, dict) else raw
        if not isinstance(products, list):
            raise _bad()
        result = []
        for product in products:
            if not isinstance(product, dict):
                raise _bad()
            result.append(
                {
                    "product_id": _text(
                        product.get("product_id", product.get("slug", product.get("id", product.get("_id"))))
                    ),
                    "name": _text(product.get("name")),
                    "countries": _countries(product),
                    "in_stock": product.get("in_stock") is True,
                }
            )
        return result

    async def details(self, product_id: str) -> dict:
        data = await self._call("get-product-details", {"product_id": product_id, "currency": "USD"})
        if not isinstance(data, dict):
            raise _bad()
        actual_id = data.get("product_id", data.get("id", data.get("_id")))
        if actual_id != product_id:
            raise _bad("Provider returned a different product.")
        recipient_type = data.get("recipient_type")
        if recipient_type not in {"none", "phone_number", "account", "email", "username"}:
            raise _bad("Product recipient requirements could not be verified.")
        if data.get("prepayment"):
            raise ProviderError(
                "UNSUPPORTED_PRODUCT", "Products requiring prepayment forms are outside this minimal flow."
            )
        raw_methods = data.get("payment_methods")
        if isinstance(raw_methods, dict):
            if any(not isinstance(values, list) for values in raw_methods.values()):
                raise _bad()
            methods = [method for values in raw_methods.values() for method in values]
        elif isinstance(raw_methods, list):
            methods = raw_methods
        else:
            raise _bad("Provider did not supply payment methods.")
        if any(not isinstance(method, str) for method in methods):
            raise _bad()
        packages = data.get("packages")
        if not isinstance(packages, list) or not packages:
            raise _bad("Provider did not supply exact denominations and prices.")
        normalized_packages = []
        for package in packages:
            if not isinstance(package, dict):
                raise _bad()
            price = _decimal(package.get("payment_price"))
            currency = _text(package.get("payment_currency"), maximum=8)
            if currency != currency.upper():
                raise _bad()
            normalized_packages.append(
                {
                    "package_value": _text(package.get("package_value")),
                    "payment_price": str(price),
                    "payment_currency": currency,
                }
            )
        if len({p["package_value"] for p in normalized_packages}) != len(normalized_packages):
            raise _bad("Provider returned ambiguous denominations.")
        return {
            "product_id": product_id,
            "name": _text(data.get("name")),
            "countries": _countries(data),
            "recipient_type": recipient_type,
            "in_stock": data.get("in_stock") is True,
            "payment_methods": sorted(set(methods) & MANUAL_METHODS),
            "packages": normalized_packages,
        }

    async def create_invoice(self, action: dict) -> dict:
        if action.get("payment_method") not in MANUAL_METHODS or action.get("quantity") != 1:
            raise ProviderError(
                "PAYMENT_METHOD_DENIED", "Only a single-item manual crypto checkout is allowed."
            )

        def arguments(schema: dict) -> dict:
            properties = schema.get("properties", {})
            if not {"cart_items", "payment_method", "email"}.issubset(properties):
                # Silently omitting payment_method could select an upstream
                # auto-debit default, so a schema change must stop the call.
                raise ProviderError(
                    "PROVIDER_SCHEMA", "Bitrefill's checkout authority fields are unsupported."
                )
            item_schema = properties.get("cart_items", {}).get("items", {})
            item_properties = item_schema.get("properties", {})
            if "package_value" in item_properties:
                denomination_key = "package_value"
            elif "package_id" in item_properties:
                denomination_key = "package_id"
            else:
                raise ProviderError("PROVIDER_SCHEMA", "Bitrefill's denomination schema is unsupported.")
            item = {"product_id": action["product_id"], denomination_key: action["package_value"]}
            if action.get("recipient"):
                if "refill_input" not in item_properties:
                    raise ProviderError("PROVIDER_SCHEMA", "Bitrefill's recipient schema is unsupported.")
                item["refill_input"] = action["recipient"]
            return {
                "cart_items": [item],
                "payment_method": action["payment_method"],
                "return_payment_link": True,
                "email": action["email"],
            }

        result = await self._call("buy-products", arguments)
        return normalize_invoice(result)

    async def invoice(self, invoice_id: str, access_token: str | None = None) -> dict:
        args = {"invoice_id": invoice_id}
        if access_token:
            args["invoice_access_token"] = access_token
        return normalize_invoice(await self._call("get-invoice-by-id", args), expected_id=invoice_id)


def _http_status(exc: BaseException) -> int | None:
    """Find HTTP errors inside anyio task-group exceptions, without logging."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    for nested in getattr(exc, "exceptions", ()):
        status = _http_status(nested)
        if status is not None:
            return status
    return None

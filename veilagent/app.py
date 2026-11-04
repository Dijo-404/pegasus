from contextlib import asynccontextmanager
import hmac
import time
import uuid

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import STATIC_DIR, Settings
from .errors import Denied
from .service import CommerceService
from .store import Store


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Proposal(StrictBody):
    product_id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    package_value: str = Field(min_length=1, max_length=120)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    recipient: str = Field(default="", max_length=254)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    payment_method: str = Field(max_length=40)
    max_total_minor: int = Field(gt=0, le=100000)


class Approval(StrictBody):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Execution(StrictBody):
    grant: str = Field(min_length=10, max_length=8192)


def create_app(settings=None, provider=None, zcash=None):
    settings = settings or Settings.from_env()
    from .providers.bitrefill import BitrefillClient, ProviderError
    from .providers.zcash import ZcashClient, ZcashError, payment_uri

    store = Store(settings.database_path, settings.data_key)
    provider = provider or BitrefillClient(settings.bitrefill_api_key)
    zcash = zcash or ZcashClient(settings.zcash_graphql_url, settings.zcash_account_id, settings.zcash_confirmations)
    service = CommerceService(settings, store, provider)

    @asynccontextmanager
    async def lifespan(app):
        yield

    app = FastAPI(title="VeilAgent", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.service = store, service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def boundary(request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": {"code": "ORIGIN_DENIED", "message": "Same-origin requests required."}}, 403)
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"error": {"code": "INVALID_INPUT", "message": "Invalid content length."}}, 400)
        if length > 16384:
            return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": "Request too large."}}, 413)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 16384:
                return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": "Request too large."}}, 413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(Denied)
    async def denied_handler(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        # Pydantic's default response echoes user input, possibly including credentials or PII.
        return JSONResponse({"error": {"code": "INVALID_INPUT", "message": "Request fields have invalid values or unexpected fields."}}, 422)

    @app.exception_handler(ProviderError)
    @app.exception_handler(ZcashError)
    async def provider_handler(request, error):
        return JSONResponse({"error": {"code": error.code, "message": str(error)}}, 502)

    def actor(request: Request):
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if hmac.compare_digest(token.encode(), settings.owner_token.encode()):
            return "owner"
        if hmac.compare_digest(token.encode(), settings.agent_token.encode()):
            return "agent"
        raise Denied("UNAUTHORIZED", "A local owner or agent bearer token is required.", 401)

    def owner(role=Depends(actor)):
        if role != "owner":
            raise Denied("OWNER_REQUIRED", "Exact purchase approval requires the separate owner credential.", 403)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/config")
    async def config():
        return {"mode": "live", "bitrefill_configured": bool(settings.bitrefill_api_key),
                "zcash_configured": settings.zcash_enabled,
                "caps": {"per_purchase_minor": settings.max_purchase_minor, "per_day_minor": settings.max_daily_minor,
                         "currency": "USD", "day_timezone": "Asia/Kolkata"},
                "allowed_products": sorted(settings.allowed_products), "allowed_countries": sorted(settings.allowed_countries),
                "merchant": {"name": "VeilAgent private demo resource", "amount_zats": settings.zcash_amount_zats}}

    @app.get("/api/catalog/search", dependencies=[Depends(actor)])
    async def search(q: str = Query(min_length=1, max_length=200), country: str = "IN", intent: str = "User-requested shopping"):
        if country not in settings.allowed_countries or len(intent) > 500:
            raise Denied("COUNTRY_DENIED", "Search is outside the configured policy.")
        return {"products": await provider.search(q, country, intent)}

    @app.get("/api/catalog/products/{product_id}", dependencies=[Depends(actor)])
    async def details(product_id: str):
        if product_id not in settings.allowed_products:
            raise Denied("PRODUCT_DENIED", "Product is outside the local allowlist.")
        return await provider.details(product_id)

    @app.post("/api/intents")
    async def propose(body: Proposal, role=Depends(actor)):
        return service.public(await service.propose(body.model_dump()), owner=role == "owner")

    @app.get("/api/intents")
    async def intents(role=Depends(actor)):
        return {"intents": [service.public(value, owner=role == "owner") for value in store.list_intents()]}

    @app.get("/api/intents/{intent_id}")
    async def get_intent(intent_id: str, role=Depends(actor)):
        return service.public(store.intent(intent_id), owner=role == "owner")

    @app.post("/api/intents/{intent_id}/approve", dependencies=[Depends(owner)])
    async def approve(intent_id: str, body: Approval):
        return service.approve(intent_id, body.digest)

    @app.post("/api/intents/{intent_id}/execute")
    async def execute(intent_id: str, body: Execution, role=Depends(actor)):
        await service.execute(intent_id, body.grant)
        return service.public(store.intent(intent_id), owner=role == "owner")

    @app.post("/api/intents/{intent_id}/refresh")
    async def refresh(intent_id: str, role=Depends(actor)):
        await service.refresh(intent_id)
        return service.public(store.intent(intent_id), owner=role == "owner")

    @app.get("/api/intents/{intent_id}/audit", dependencies=[Depends(actor)])
    async def audit(intent_id: str):
        return {"events": store.audit(intent_id)}

    def private_enabled():
        if not settings.zcash_enabled:
            raise Denied("ZCASH_NOT_CONFIGURED", "Enable the local testnet receiver in .env first.", 503)

    @app.post("/api/private/orders", dependencies=[Depends(actor)])
    async def private_order(body: StrictBody):
        private_enabled()
        address = await zcash.address()
        order_id = "zo_" + uuid.uuid4().hex
        memo = "VEIL-" + uuid.uuid4().hex
        order = {"id": order_id, "memo": memo, "address": address, "amount_zats": settings.zcash_amount_zats,
                 "payment_uri": payment_uri(address, settings.zcash_amount_zats, memo),
                 "status": "AWAITING_PAYMENT", "created_at": int(time.time()), "payment": None}
        store.insert_private(order)
        return order

    @app.post("/api/private/orders/{order_id}/refresh", dependencies=[Depends(actor)])
    async def private_refresh(order_id: str):
        private_enabled()
        order = store.private(order_id)
        if order["status"] == "AWAITING_PAYMENT":
            payment = await zcash.find_payment(order["memo"], order["amount_zats"])
            if payment:
                return store.confirm_private(order_id, payment)
        return order

    @app.post("/api/private/orders/{order_id}/redeem", dependencies=[Depends(actor)])
    async def redeem(order_id: str):
        private_enabled()
        store.redeem(order_id)
        return {"content": "Welcome to the VeilAgent private resource. Your shielded testnet payment was independently verified and this single-use entitlement is now consumed."}

    app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app

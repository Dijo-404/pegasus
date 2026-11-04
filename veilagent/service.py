from datetime import datetime
import time
import uuid
from zoneinfo import ZoneInfo

from .errors import Denied
from .policy import invoice_status, invoice_verified, validate_quote
from .security import digest, sign, verify


class CommerceService:
    def __init__(self, settings, store, provider):
        self.settings, self.store, self.provider = settings, store, provider

    async def propose(self, request):
        # Reject allowlist failures before any external call.
        if request["product_id"] not in self.settings.allowed_products:
            raise Denied("PRODUCT_DENIED", "Product is outside the local allowlist.")
        details = await self.provider.details(request["product_id"])
        action = validate_quote(request, details, self.settings)
        now = int(time.time())
        intent = {"id": "pi_" + uuid.uuid4().hex, "action": action, "digest": digest(action),
                  "status": "AWAITING_APPROVAL", "created_at": now,
                  "expires_at": now + self.settings.quote_ttl_seconds, "invoice": None}
        self.store.insert_intent(intent)
        return intent

    def approve(self, intent_id, expected_digest):
        grant_id, expires = self.store.approve(intent_id, expected_digest, self.settings.grant_ttl_seconds)
        intent = self.store.intent(intent_id)
        now = int(time.time())
        claims = {"v": 1, "iss": "veilagent", "aud": "execution-gateway", "sub": "local-owner",
                  "agent": "local-agent", "action": "bitrefill.create_invoice", "jti": grant_id,
                  "intent_id": intent_id, "digest": intent["digest"], "nbf": now, "exp": expires,
                  "max_total_minor": intent["action"]["max_total_minor"], "currency": "USD"}
        return {"grant": sign(claims, self.settings.grant_secret), "expires_at": expires, "intent": intent}

    async def execute(self, intent_id, token):
        try:
            return await self._execute(intent_id, token)
        except Denied as error:
            self.store.event(intent_id, "execute_denied", error.code)
            raise

    async def _execute(self, intent_id, token):
        claims = verify(token, self.settings.grant_secret)
        intent = self.store.intent(intent_id)
        if (claims.get("intent_id") != intent_id or claims.get("digest") != intent["digest"]
                or claims.get("max_total_minor") != intent["action"]["max_total_minor"]
                or claims.get("currency") != intent["action"]["currency"]):
            raise Denied("INTENT_MISMATCH", "Execution grant does not match this exact intent.")
        # Check replay before contacting the catalog again; reserve remains the atomic authority.
        if intent["status"] not in {"AUTHORIZED"}:
            raise Denied("GRANT_REPLAY", "Intent already attempted or is not authorized.")
        current = validate_quote(intent["action"], await self.provider.details(intent["action"]["product_id"]), self.settings)
        # Any price change requires another exact approval, even inside the cap.
        if digest(current) != intent["digest"]:
            raise Denied("QUOTE_CHANGED", "Product terms changed. Create and approve a fresh intent.")
        day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        intent = self.store.reserve(intent_id, claims, day, self.settings.max_daily_minor)
        try:
            invoice = await self.provider.create_invoice(intent["action"])
            if not invoice.get("invoice_id"):
                raise ValueError("Missing invoice identifier")
        except Exception:
            # Conservatively ambiguous, including malformed responses and connection drops.
            # The consumed grant and budget reservation are retained indefinitely.
            intent["status"] = "UNCERTAIN"
            intent["reason"] = "PROVIDER_RESULT_UNCERTAIN"
            self.store.save_intent(intent)
            self.store.event(intent_id, "provider", "PROVIDER_RESULT_UNCERTAIN")
            return self.public(intent)
        intent["invoice"] = invoice
        intent["status"] = invoice_status(invoice) if invoice_verified(invoice, intent["action"]) else "BLOCKED"
        if intent["status"] == "BLOCKED":
            intent["reason"] = "INVOICE_TERMS_UNVERIFIED"
        self.store.save_intent(intent)
        self.store.event(intent_id, "provider", intent["status"])
        return self.public(intent)

    async def refresh(self, intent_id):
        intent = self.store.intent(intent_id)
        previous = intent["status"]
        invoice = intent.get("invoice")
        if not invoice:
            raise Denied("NO_INVOICE", "No known invoice to reconcile. Do not repeat an uncertain checkout.")
        fresh = await self.provider.invoice(invoice["invoice_id"], invoice.get("invoice_access_token"))
        if fresh.get("invoice_id") != invoice["invoice_id"]:
            raise Denied("INVOICE_MISMATCH", "Provider returned a different invoice.")
        if invoice.get("invoice_access_token"):
            fresh["invoice_access_token"] = invoice["invoice_access_token"]
        intent["invoice"] = fresh
        status = invoice_status(fresh) if invoice_verified(fresh, intent["action"]) else "BLOCKED"
        ranks = {"UNPAID": 0, "PAYMENT_DETECTED": 1, "PAYMENT_CONFIRMED": 2,
                 "PENDING_DELIVERY": 3, "DELIVERED": 4}
        if previous in {"FAILED", "EXPIRED", "DELIVERED"}:
            status = previous
        elif previous in ranks and status in ranks and ranks[status] < ranks[previous]:
            status = previous
        intent["status"] = status
        self.store.save_intent(intent)
        self.store.event(intent_id, "refresh", status)
        return self.public(intent)

    @staticmethod
    def public(intent, owner=False):
        # Explicit projection: upstream redemption codes and guest tokens never reach the planner.
        value = {key: intent[key] for key in ("id", "action", "digest", "status", "created_at", "expires_at")}
        if not owner:
            value["action"] = {**intent["action"], "recipient": "[owner only]", "email": "[owner only]"}
        value["reason"] = intent.get("reason")
        invoice = intent.get("invoice")
        value["invoice"] = None if not invoice else {
            "invoice_id": invoice["invoice_id"], "status": invoice.get("status"),
            "orders": [{"id": order.get("id"), "status": order.get("status")} for order in invoice.get("orders", [])],
            "payment_link": invoice.get("payment_link") if owner and intent["status"] == "UNPAID" else None,
            "total_minor": invoice.get("total_minor"), "currency": invoice.get("currency"),
        }
        return value

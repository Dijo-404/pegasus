"""Purchase use cases, independent of transport, persistence and signing technology."""

from datetime import datetime
import time
import uuid
from zoneinfo import ZoneInfo

from pegasus.domain.authorization_policy import GRANT_ISSUER
from pegasus.domain.canonicalization import digest
from pegasus.domain.commerce_policy import CommercePolicy, invoice_status, invoice_verified, validate_quote
from pegasus.domain.exceptions import Denied

from .ports import CommerceProvider, CommerceRepository, GrantAuthority


class CommerceService:
    def __init__(
        self,
        policy: CommercePolicy,
        repository: CommerceRepository,
        provider: CommerceProvider,
        grants: GrantAuthority,
    ):
        self.policy, self.repository, self.provider, self.grants = policy, repository, provider, grants

    async def search_catalog(self, query: str, country: str, intent: str) -> list[dict]:
        if country not in self.policy.allowed_countries or len(intent) > 500:
            raise Denied("COUNTRY_DENIED", "Search is outside the configured policy.")
        return await self.provider.search(query, country, intent)

    async def product_details(self, product_id: str) -> dict:
        if product_id not in self.policy.allowed_products:
            raise Denied("PRODUCT_DENIED", "Product is outside the local allowlist.")
        return await self.provider.details(product_id)

    def get_intent(self, intent_id: str) -> dict:
        return self.repository.intent(intent_id)

    def list_intents(self) -> list[dict]:
        return self.repository.list_intents()

    def get_audit(self, intent_id: str) -> list[dict]:
        return self.repository.audit(intent_id)

    async def propose(self, request: dict) -> dict:
        details = await self.product_details(request["product_id"])
        action = validate_quote(request, details, self.policy)
        now = int(time.time())
        intent = {
            "id": "pi_" + uuid.uuid4().hex,
            "action": action,
            "digest": digest(action),
            "status": "AWAITING_APPROVAL",
            "created_at": now,
            "expires_at": now + self.policy.quote_ttl_seconds,
            "invoice": None,
        }
        self.repository.insert_intent(intent)
        return intent

    def approve(self, intent_id: str, expected_digest: str) -> dict:
        grant_id, expires = self.repository.approve(intent_id, expected_digest, self.policy.grant_ttl_seconds)
        intent = self.repository.intent(intent_id)
        now = int(time.time())
        claims = {
            "v": 1,
            "iss": GRANT_ISSUER,
            "aud": "execution-gateway",
            "sub": "local-owner",
            "agent": "local-agent",
            "action": "bitrefill.create_invoice",
            "jti": grant_id,
            "intent_id": intent_id,
            "digest": intent["digest"],
            "nbf": now,
            "exp": expires,
            "max_total_minor": intent["action"]["max_total_minor"],
            "currency": "USD",
        }
        return {"grant": self.grants.sign(claims), "expires_at": expires, "intent": intent}

    async def execute(self, intent_id: str, token: str) -> dict:
        try:
            return await self._execute(intent_id, token)
        except Denied as error:
            self.repository.event(intent_id, "execute_denied", error.code)
            raise

    async def _execute(self, intent_id: str, token: str) -> dict:
        claims = self.grants.verify(token)
        intent = self.repository.intent(intent_id)
        if (
            claims.get("intent_id") != intent_id
            or claims.get("digest") != intent["digest"]
            or claims.get("max_total_minor") != intent["action"]["max_total_minor"]
            or claims.get("currency") != intent["action"]["currency"]
        ):
            raise Denied("INTENT_MISMATCH", "Execution grant does not match this exact intent.")
        if intent["status"] != "AUTHORIZED":
            raise Denied("GRANT_REPLAY", "Intent already attempted or is not authorized.")
        details = await self.provider.details(intent["action"]["product_id"])
        current = validate_quote(intent["action"], details, self.policy)
        if digest(current) != intent["digest"]:
            raise Denied("QUOTE_CHANGED", "Product terms changed. Create and approve a fresh intent.")
        day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        intent = self.repository.reserve(intent_id, claims, day, self.policy.max_daily_minor)
        try:
            invoice = await self.provider.create_invoice(intent["action"])
            if not invoice.get("invoice_id"):
                raise ValueError("Missing invoice identifier")
        except Exception:
            # Retain consumed authority and reserved budget across ambiguous results.
            intent["status"] = "UNCERTAIN"
            intent["reason"] = "PROVIDER_RESULT_UNCERTAIN"
            self.repository.save_intent(intent)
            self.repository.event(intent_id, "provider", "PROVIDER_RESULT_UNCERTAIN")
            return intent
        intent["invoice"] = invoice
        intent["status"] = (
            invoice_status(invoice) if invoice_verified(invoice, intent["action"]) else "BLOCKED"
        )
        if intent["status"] == "BLOCKED":
            intent["reason"] = "INVOICE_TERMS_UNVERIFIED"
        self.repository.save_intent(intent)
        self.repository.event(intent_id, "provider", intent["status"])
        return intent

    async def refresh(self, intent_id: str) -> dict:
        intent = self.repository.intent(intent_id)
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
        ranks = {
            "UNPAID": 0,
            "PAYMENT_DETECTED": 1,
            "PAYMENT_CONFIRMED": 2,
            "PENDING_DELIVERY": 3,
            "DELIVERED": 4,
        }
        if previous in {"FAILED", "EXPIRED", "DELIVERED"}:
            status = previous
        elif previous in ranks and status in ranks and ranks[status] < ranks[previous]:
            status = previous
        intent["status"] = status
        self.repository.save_intent(intent)
        self.repository.event(intent_id, "refresh", status)
        return intent

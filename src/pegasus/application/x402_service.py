"""Owner-approved external API payments with one reserved execution attempt."""

import asyncio
from copy import deepcopy
from datetime import datetime
import json
import time
import uuid
from zoneinfo import ZoneInfo

from pegasus.domain.authorization_policy import GRANT_ISSUER
from pegasus.domain.canonicalization import digest
from pegasus.domain.exceptions import Denied
from pegasus.domain.x402_policy import (
    X402_ACTION,
    X402Policy,
    settlement_verified,
    validate_quote,
    validate_request,
)

from .ports import CommerceRepository, GrantAuthority, X402PaymentProvider


class X402Service:
    def __init__(
        self,
        policy: X402Policy,
        repository: CommerceRepository,
        provider: X402PaymentProvider,
        grants: GrantAuthority,
    ):
        self.policy, self.repository, self.provider, self.grants = policy, repository, provider, grants

    def _require_enabled(self) -> None:
        if not self.policy.enabled:
            raise Denied("X402_DISABLED", "External API payments are not configured.")

    def get_intent(self, intent_id: str) -> dict:
        intent = self.repository.intent(intent_id)
        if intent.get("kind") != "x402" or not intent.get("id", "").startswith("xi_"):
            raise Denied("NOT_FOUND", "API payment intent not found.")
        return intent

    def list_intents(self) -> list[dict]:
        return [
            intent for intent in self.repository.list_intents()
            if intent.get("kind") == "x402" and intent.get("id", "").startswith("xi_")
        ]

    def get_audit(self, intent_id: str) -> list[dict]:
        self.get_intent(intent_id)
        return self.repository.audit(intent_id)

    async def propose(self, request: dict) -> dict:
        url = validate_request(request, self.policy)
        challenge = await self.provider.discover(url)
        action = validate_quote(request, challenge, self.policy)
        now = int(time.time())
        intent = {
            "id": "xi_" + uuid.uuid4().hex,
            "kind": "x402",
            "action": action,
            "digest": digest(action),
            "status": "AWAITING_APPROVAL",
            "created_at": now,
            "expires_at": now + self.policy.quote_ttl_seconds,
            "result": None,
            "settlement": None,
        }
        self.repository.insert_intent(intent)
        return intent

    def approve(self, intent_id: str, expected_digest: str) -> dict:
        self._require_enabled()
        self.get_intent(intent_id)  # Refuse cross-rail approval before any repository mutation.
        grant_id, expires = self.repository.approve(intent_id, expected_digest, self.policy.grant_ttl_seconds)
        intent = self.get_intent(intent_id)
        now = int(time.time())
        claims = {
            "v": 1,
            "iss": GRANT_ISSUER,
            "aud": "execution-gateway",
            "sub": "local-owner",
            "agent": "local-agent",
            "action": X402_ACTION,
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
            self.repository.event(intent_id, "x402_execute_denied", error.code)
            raise

    async def _execute(self, intent_id: str, token: str) -> dict:
        self._require_enabled()
        claims = self.grants.verify(token)
        intent = self.get_intent(intent_id)
        action = intent["action"]
        if (
            claims.get("action") != X402_ACTION
            or action.get("type") != X402_ACTION
            or claims.get("intent_id") != intent_id
            or claims.get("digest") != intent["digest"]
            or digest(action) != intent["digest"]
            or type(claims.get("max_total_minor")) is not int
            or claims["max_total_minor"] != action["max_total_minor"]
            or claims.get("currency") != "USD"
            or action.get("currency") != "USD"
        ):
            raise Denied("INTENT_MISMATCH", "Execution grant does not match this exact API payment.")
        if intent["status"] != "AUTHORIZED":
            raise Denied("GRANT_REPLAY", "This API payment was already attempted or is not authorized.")
        request = {"url": action["url"], "max_total_minor": action["max_total_minor"]}
        validate_request(request, self.policy)
        fresh = await self.provider.discover(action["url"])
        current = validate_quote(request, fresh, self.policy)
        if digest(current) != intent["digest"]:
            raise Denied("QUOTE_CHANGED", "API payment terms changed. Create and approve a fresh intent.")
        day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        intent = self.repository.reserve(intent_id, claims, day, self.policy.max_daily_minor)
        try:
            outcome = await self.provider.pay(deepcopy(intent["action"]))
            if (
                not isinstance(outcome, dict)
                or outcome.get("status") != "SUCCEEDED"
                or not settlement_verified(outcome.get("settlement"), intent["action"])
            ):
                raise ValueError("Unverified payment outcome")
            result = self._safe_result(outcome.get("result"))
            settlement = outcome["settlement"]
            intent["result"] = result
            intent["settlement"] = {
                key: settlement[key] for key in (
                    "network", "transaction", "payer", "asset", "pay_to", "amount_atomic",
                    "verified", "authorization_verified", "block_number",
                )
            }
        except asyncio.CancelledError:
            self._uncertain(intent)
            raise
        except Exception:
            return self._uncertain(intent)
        intent["status"] = "SUCCEEDED"
        self.repository.save_intent(intent)
        self.repository.event(intent_id, "x402_provider", "SUCCEEDED")
        return intent

    @staticmethod
    def _safe_result(result: dict) -> dict:
        if not isinstance(result, dict) or set(result) != {"content_type", "body"}:
            raise ValueError("Missing bounded API result")
        content_type = result["content_type"]
        if (
            not isinstance(content_type, str)
            or not 1 <= len(content_type) <= 128
            or any(ord(character) < 32 or ord(character) == 127 for character in content_type)
        ):
            raise ValueError("Invalid result content type")
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("API result too large")
        return json.loads(encoded)

    def _uncertain(self, intent: dict) -> dict:
        # Never reuse signed authority or release its shared-budget reservation.
        intent.update(
            status="UNCERTAIN", reason="PAYMENT_RESULT_UNCERTAIN", result=None, settlement=None
        )
        self.repository.save_intent(intent)
        self.repository.event(intent["id"], "x402_provider", "PAYMENT_RESULT_UNCERTAIN")
        return intent

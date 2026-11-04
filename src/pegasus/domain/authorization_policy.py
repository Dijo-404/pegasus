"""Approval and spend invariants evaluated inside the repository's transaction."""

from .exceptions import Denied

GRANT_ISSUER = "pegasus"


def approval_expiry(intent: dict, expected_digest: str, now: int, ttl: int) -> int:
    if intent["digest"] != expected_digest:
        raise Denied("APPROVAL_MISMATCH", "Approval does not match the displayed intent.")
    if intent["status"] != "AWAITING_APPROVAL":
        raise Denied("ALREADY_APPROVED", "This intent cannot be approved again.")
    if intent["expires_at"] <= now:
        raise Denied("QUOTE_EXPIRED", "Quote expired. Create a fresh intent.")
    return min(now + ttl, intent["expires_at"])


def validate_reservation(intent: dict, grant: dict | None, now: int) -> None:
    if grant is None or grant["intent_id"] != intent["id"] or grant["digest"] != intent["digest"]:
        raise Denied("INVALID_GRANT", "Grant is not bound to this intent.")
    if grant["consumed_at"] is not None:
        raise Denied("GRANT_REPLAY", "Grant already consumed. No second purchase was attempted.")
    if grant["expires_at"] <= now or intent["expires_at"] <= now:
        raise Denied("GRANT_EXPIRED", "This approval expired.")
    if intent["status"] != "AUTHORIZED":
        raise Denied("INVALID_STATE", "Intent is not executable.")


def validate_daily_budget(reserved_minor: int, amount_minor: int, cap_minor: int) -> None:
    if reserved_minor + amount_minor > cap_minor:
        raise Denied("DAILY_CAP", "Daily reserved spend cap reached. Nothing was purchased.")

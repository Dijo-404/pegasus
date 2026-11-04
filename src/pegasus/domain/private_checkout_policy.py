"""Independent shielded-resource checkout rules."""

from dataclasses import dataclass

from .exceptions import Denied


@dataclass(frozen=True)
class PrivateCheckoutPolicy:
    enabled: bool
    amount_zats: int


def validate_redemption(order: dict, now: int) -> None:
    if order["status"] != "CONFIRMED":
        raise Denied("NOT_REDEEMABLE", "A confirmed payment and unused entitlement are required.")
    if order.get("entitlement_expires_at", 0) <= now:
        raise Denied("ENTITLEMENT_EXPIRED", "The five-minute entitlement expired.")

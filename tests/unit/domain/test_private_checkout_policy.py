import pytest

from pegasus.domain.exceptions import Denied
from pegasus.domain.private_checkout_policy import validate_redemption


@pytest.mark.parametrize("status", ["AWAITING_PAYMENT", "REDEEMED", "FAILED"])
def test_only_confirmed_unused_entitlements_can_redeem(status):
    with pytest.raises(Denied) as error:
        validate_redemption({"status": status, "entitlement_expires_at": 2000}, now=1000)
    assert error.value.code == "NOT_REDEEMABLE"


@pytest.mark.parametrize("expiry", [None, 999, 1000])
def test_redemption_fails_at_expiry_or_without_an_expiry(expiry):
    order = {"status": "CONFIRMED"}
    if expiry is not None:
        order["entitlement_expires_at"] = expiry
    with pytest.raises(Denied) as error:
        validate_redemption(order, now=1000)
    assert error.value.code == "ENTITLEMENT_EXPIRED"


def test_unexpired_confirmed_entitlement_can_redeem():
    validate_redemption({"status": "CONFIRMED", "entitlement_expires_at": 1001}, now=1000)

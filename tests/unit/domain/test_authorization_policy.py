"""Authorization boundaries remain independent of the persistence transaction."""

import pytest

from pegasus.domain.authorization_policy import approval_expiry, validate_daily_budget, validate_reservation
from pegasus.domain.exceptions import Denied


NOW = 1000


def intent(**changes):
    return {
        "id": "intent",
        "digest": "approved-digest",
        "status": "AUTHORIZED",
        "expires_at": NOW + 100,
        **changes,
    }


def grant(**changes):
    return {
        "intent_id": "intent",
        "digest": "approved-digest",
        "consumed_at": None,
        "expires_at": NOW + 90,
        **changes,
    }


def test_approval_cannot_outlive_its_quote():
    awaiting = intent(status="AWAITING_APPROVAL")
    assert approval_expiry(awaiting, "approved-digest", NOW, ttl=200) == NOW + 100
    assert approval_expiry(awaiting, "approved-digest", NOW, ttl=90) == NOW + 90


@pytest.mark.parametrize(
    "changes,digest,code",
    [
        ({}, "different-digest", "APPROVAL_MISMATCH"),
        ({"status": "AUTHORIZED"}, "approved-digest", "ALREADY_APPROVED"),
        ({"expires_at": NOW}, "approved-digest", "QUOTE_EXPIRED"),
    ],
)
def test_approval_rejects_mismatch_reuse_and_expired_quote(changes, digest, code):
    with pytest.raises(Denied) as error:
        approval_expiry(intent(**{"status": "AWAITING_APPROVAL", **changes}), digest, NOW, ttl=90)
    assert error.value.code == code


@pytest.mark.parametrize(
    "record,changes,code",
    [
        (None, {}, "INVALID_GRANT"),
        (grant(intent_id="other-intent"), {}, "INVALID_GRANT"),
        (grant(digest="other-digest"), {}, "INVALID_GRANT"),
        (grant(consumed_at=0), {}, "GRANT_REPLAY"),
        (grant(expires_at=NOW), {}, "GRANT_EXPIRED"),
        (grant(), {"expires_at": NOW}, "GRANT_EXPIRED"),
        (grant(), {"status": "EXECUTING"}, "INVALID_STATE"),
    ],
)
def test_reservation_fails_closed(record, changes, code):
    with pytest.raises(Denied) as error:
        validate_reservation(intent(**changes), record, NOW)
    assert error.value.code == code


def test_daily_cap_allows_exact_boundary_and_denies_one_cent_more():
    validate_daily_budget(reserved_minor=989, amount_minor=11, cap_minor=1000)
    with pytest.raises(Denied) as error:
        validate_daily_budget(reserved_minor=990, amount_minor=11, cap_minor=1000)
    assert error.value.code == "DAILY_CAP"

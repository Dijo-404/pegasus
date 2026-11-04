"""Pure purchase-policy rules have no HTTP, storage or provider dependencies."""

import pytest

from pegasus.domain.canonicalization import digest
from pegasus.domain.commerce_policy import invoice_status, minor_units
from pegasus.domain.exceptions import Denied


def test_money_is_exact():
    assert minor_units("0.11", "USD") == 11
    for value, currency in (
        ("0.001", "USD"),
        ("NaN", "USD"),
        ("Infinity", "USD"),
        ("1", "INR"),
        ("-1", "USD"),
    ):
        with pytest.raises(Denied):
            minor_units(value, currency)


def test_canonical_digest_does_not_depend_on_dictionary_order():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_unpaid_invoice_is_reported_truthfully():
    assert invoice_status({"status": "unpaid", "orders": []}) == "UNPAID"


@pytest.mark.parametrize("state", ["unpaid", "unknown"])
def test_delivered_order_with_unpaid_invoice_is_blocked(state):
    invoice = {"status": state, "orders": [{"id": "fixture", "status": "delivered"}]}
    assert invoice_status(invoice) == "BLOCKED"

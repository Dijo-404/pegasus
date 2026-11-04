"""Pure purchase-policy rules have no HTTP, storage or provider dependencies."""

from copy import deepcopy
from dataclasses import replace

import pytest

from pegasus.domain.canonicalization import digest
from pegasus.domain.commerce_policy import (
    CommercePolicy, invoice_status, invoice_verified, minor_units, validate_quote,
)
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


@pytest.fixture
def receipt_checkout():
    request = {
        "product_id": "demo-product", "package_value": "10", "country": "IN",
        "recipient": "", "email": "owner@example.invalid", "payment_method": "lightning",
        "max_total_minor": 11,
    }
    details = {
        "product_id": "demo-product", "countries": ["IN"], "in_stock": True,
        "payment_methods": ["lightning"], "recipient_type": "none",
        "packages": [{"package_value": "10", "payment_price": "0.11", "payment_currency": "USD"}],
    }
    policy = CommercePolicy(
        500, 1000, frozenset({"demo-product"}), frozenset({"IN"}),
        frozenset({"owner@example.invalid"}), frozenset(), 300, 90,
    )
    return request, details, policy


def test_email_receipt_keeps_existing_canonical_action(receipt_checkout):
    request, details, policy = receipt_checkout
    action = validate_quote(request, details, policy)
    explicit = validate_quote(
        {**request, "receipt_mode": "email", "receipt_account_reference": None},
        {**details, "receipt_destination": {"mode": "email"}}, policy,
    )
    assert action == {
        "schema_version": 1, "product_id": "demo-product", "package_value": "10", "quantity": 1,
        "country": "IN", "recipient_type": "none", "recipient": "", "email": "owner@example.invalid",
        "payment_method": "lightning", "currency": "USD", "total_minor": 11, "max_total_minor": 11,
    }
    assert digest(action) == digest(explicit)


def test_account_receipt_binds_reference_without_an_email_allowlist(receipt_checkout):
    request, details, policy = receipt_checkout
    reference = "sha256:" + "a" * 64
    request.update(email="", receipt_mode="provider_account", receipt_account_reference=reference)
    details["receipt_destination"] = {"mode": "provider_account", "account_reference": reference}
    action = validate_quote(request, details, replace(policy, allowed_emails=frozenset()))
    assert action["email"] == ""
    assert action["receipt_mode"] == "provider_account"
    assert action["receipt_account_reference"] == reference
    next_reference = "sha256:" + "b" * 64
    updated = validate_quote(
        {**request, "receipt_account_reference": next_reference},
        {**details, "receipt_destination": {"mode": "provider_account", "account_reference": next_reference}},
        policy,
    )
    assert digest(action) != digest(updated)


@pytest.mark.parametrize(
    "mode,email,request_ref,provider_mode,provider_ref,code",
    [
        ("unknown", "", None, "email", None, "RECEIPT_MODE_DENIED"),
        ("email", "owner@example.invalid", None, "provider_account", "sha256:" + "a" * 64,
         "RECEIPT_MODE_MISMATCH"),
        ("provider_account", "", "sha256:" + "a" * 64, "email", None, "RECEIPT_MODE_MISMATCH"),
        ("provider_account", "", None, "provider_account", "sha256:" + "a" * 64,
         "RECEIPT_ACCOUNT_MISMATCH"),
        ("provider_account", "", "sha256:" + "b" * 64, "provider_account", "sha256:" + "a" * 64,
         "RECEIPT_ACCOUNT_MISMATCH"),
        ("provider_account", "owner@example.invalid", "sha256:" + "a" * 64, "provider_account",
         "sha256:" + "a" * 64, "RECEIPT_EMAIL_UNEXPECTED"),
        ("provider_account", "", "sha256:" + "A" * 64, "provider_account", "sha256:" + "A" * 64,
         "RECEIPT_UNVERIFIED"),
        ("email", "", None, "email", None, "EMAIL_DENIED"),
        ("email", "attacker@example.invalid", None, "email", None, "EMAIL_DENIED"),
        ("email", "owner@example.invalid", "sha256:" + "a" * 64, "email", None,
         "RECEIPT_ACCOUNT_UNEXPECTED"),
        ("email", "owner@example.invalid", None, "unknown", None, "RECEIPT_UNVERIFIED"),
    ],
)
def test_receipt_mode_and_account_changes_fail_closed(
    receipt_checkout, mode, email, request_ref, provider_mode, provider_ref, code,
):
    request, details, policy = receipt_checkout
    request.update(email=email, receipt_mode=mode, receipt_account_reference=request_ref)
    details["receipt_destination"] = {"mode": provider_mode, "account_reference": provider_ref}
    with pytest.raises(Denied) as error:
        validate_quote(request, details, policy)
    assert error.value.code == code


def test_invoice_receipt_terms_cannot_switch_between_email_and_account(receipt_checkout):
    request, details, policy = receipt_checkout
    guest_action = validate_quote(request, details, policy)
    reference = "sha256:" + "a" * 64
    account_action = validate_quote(
        {**request, "email": "", "receipt_mode": "provider_account", "receipt_account_reference": reference},
        {**details, "receipt_destination": {"mode": "provider_account", "account_reference": reference}}, policy,
    )
    items = [{"product_id": "demo-product", "package_value": "10", "quantity": 1, "recipient": ""}]
    guest_invoice = {
        "total_minor": 11, "currency": "USD",
        "verified_terms": {"items": items, "email": request["email"], "payment_method": "lightning"},
    }
    account_invoice = {
        "total_minor": 11, "currency": "USD",
        "verified_terms": {
            "items": items, "payment_method": "lightning",
            "receipt_destination": {"mode": "provider_account", "account_reference": reference},
        },
    }
    assert invoice_verified(guest_invoice, guest_action)
    assert invoice_verified(account_invoice, account_action)
    assert not invoice_verified(guest_invoice, account_action)
    assert not invoice_verified(account_invoice, guest_action)
    altered = deepcopy(account_invoice)
    altered["verified_terms"]["receipt_destination"]["account_reference"] = "sha256:" + "b" * 64
    assert not invoice_verified(altered, account_action)
    altered = deepcopy(account_invoice)
    altered["verified_terms"]["email"] = "invented@example.invalid"
    assert not invoice_verified(altered, account_action)


def test_complete_invoice_needs_delivered_order_status():
    assert invoice_status({"status": "complete", "orders": []}) == "PENDING_DELIVERY"
    assert invoice_status({"status": "complete", "orders": [{"status": "pending"}]}) == "PENDING_DELIVERY"
    assert invoice_status({"status": "complete", "orders": [{"status": "delivered"}]}) == "DELIVERED"

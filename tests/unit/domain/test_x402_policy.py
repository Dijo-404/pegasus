"""Pure x402 policy tests: no SDK, HTTP, wallet, or network access."""

from copy import deepcopy

import pytest

from pegasus.domain.canonicalization import digest
from pegasus.domain.exceptions import Denied
from pegasus.domain.x402_policy import (
    BASE_SEPOLIA_NETWORK,
    BASE_SEPOLIA_USDC,
    X402Policy,
    settlement_verified,
    validate_quote,
    validate_request,
)

URL = "https://api.example.com/private/data?q=one"
PAYEE = "0x" + "12" * 20


def policy(**changes):
    return X402Policy(
        **{
            "enabled": True,
            "allowed_origins": frozenset({"https://api.example.com"}),
            "allowed_payees": frozenset({PAYEE}),
            **changes,
        }
    )


def request(**changes):
    return {"url": URL, "max_total_minor": 2, **changes}


def challenge(**requirement_changes):
    return {
        "x402Version": 2,
        "resource": {"url": URL, "description": "Example test API", "mimeType": "application/json"},
        "accepts": [{
            "scheme": "exact",
            "network": BASE_SEPOLIA_NETWORK,
            "asset": BASE_SEPOLIA_USDC,
            "payTo": PAYEE,
            "amount": "10001",
            "maxTimeoutSeconds": 300,
            "extra": {"name": "USDC", "version": "2"},
            **requirement_changes,
        }],
    }


def test_exact_action_uses_integer_cent_ceiling_and_copies_all_selected_terms():
    original = challenge()
    action = validate_quote(request(), original, policy())
    assert action["type"] == "x402.pay_request"
    assert action["method"] == "GET"
    assert action["total_minor"] == 2  # Fractional cents round UP; never float conversion.
    assert action["amount_atomic"] == "10001"
    assert action["payment_requirements"] == original["accepts"][0]
    assert action["resource"] == original["resource"]
    before = digest(action)
    original["accepts"][0]["extra"]["version"] = "changed"
    original["resource"]["description"] = "changed"
    assert digest(action) == before


@pytest.mark.parametrize("url", [
    "http://api.example.com/data", "https://127.0.0.1/data", "https://[::1]/data",
    "https://localhost/data", "https://api.local/data", "https://api.internal/data",
    "https://api.example.com:8443/data", "https://user@api.example.com/data",
    "https://user:secret@api.example.com/data", "https://api.example.com/data#fragment",
    "https://api.example.com/data#", "https://api.example.com\\@evil.com/data",
    "https://api.example.com/data\n", "https://api.example.com.evil.com/data",
    "https://other.example.com/data", "https://api.example.com./data",
    "https://2130706433/data", "https://0177.0.0.1/data",
])
def test_nonpublic_or_nonallowlisted_urls_are_rejected(url):
    with pytest.raises(Denied):
        validate_request(request(url=url), policy())


def test_default_https_port_is_the_same_origin_but_url_remains_exact():
    url = "https://api.example.com:443/data"
    assert validate_request(request(url=url), policy()) == url


@pytest.mark.parametrize("maximum", [True, False, "2", 2.0, None, 0, -1, 501])
def test_ceiling_requires_a_positive_strict_integer_within_policy(maximum):
    with pytest.raises(Denied) as error:
        validate_request(request(max_total_minor=maximum), policy())
    assert error.value.code == "PURCHASE_CAP"


@pytest.mark.parametrize("field,value,code", [
    ("scheme", "upto", "X402_SCHEME_DENIED"),
    ("network", "eip155:8453", "X402_NETWORK_DENIED"),
    ("network", "eip155:1", "X402_NETWORK_DENIED"),
    ("extra", {"assetTransferMethod": "permit2"}, "X402_TRANSFER_METHOD_DENIED"),
    ("extra", {"assetTransferMethod": "other"}, "X402_TRANSFER_METHOD_DENIED"),
    ("extra", None, "X402_TRANSFER_METHOD_DENIED"),
    ("extra", [], "X402_TRANSFER_METHOD_DENIED"),
    ("extra", {"name": "Different token"}, "X402_TOKEN_DOMAIN_DENIED"),
    ("extra", {"name": None}, "X402_TOKEN_DOMAIN_DENIED"),
    ("extra", {"version": "3"}, "X402_TOKEN_DOMAIN_DENIED"),
    ("extra", {"version": 2}, "X402_TOKEN_DOMAIN_DENIED"),
    ("asset", "0x" + "ff" * 20, "X402_ASSET_DENIED"),
    ("payTo", "0x" + "34" * 20, "X402_PAYEE_DENIED"),
    ("payTo", "0x" + "00" * 20, "X402_PAYEE_DENIED"),
    ("payTo", "not-an-address", "X402_PAYEE_DENIED"),
    ("amount", 10000, "X402_INVALID_AMOUNT"),
    ("amount", True, "X402_INVALID_AMOUNT"),
    ("amount", 10000.0, "X402_INVALID_AMOUNT"),
    ("amount", "01", "X402_INVALID_AMOUNT"),
    ("amount", "1.0", "X402_INVALID_AMOUNT"),
    ("amount", "1e4", "X402_INVALID_AMOUNT"),
    ("amount", "0", "X402_INVALID_AMOUNT"),
    ("amount", "-1", "X402_INVALID_AMOUNT"),
    ("amount", "9" * 79, "X402_INVALID_AMOUNT"),
    ("amount", str(2**256), "X402_INVALID_AMOUNT"),
    ("amount", "20001", "PURCHASE_CAP"),
    ("maxTimeoutSeconds", True, "X402_TIMEOUT_DENIED"),
    ("maxTimeoutSeconds", "60", "X402_TIMEOUT_DENIED"),
    ("maxTimeoutSeconds", 60.0, "X402_TIMEOUT_DENIED"),
    ("maxTimeoutSeconds", 0, "X402_TIMEOUT_DENIED"),
    ("maxTimeoutSeconds", 301, "X402_TIMEOUT_DENIED"),
])
def test_unsupported_or_unsafe_requirements_are_denied(field, value, code):
    with pytest.raises(Denied) as error:
        validate_quote(request(), challenge(**{field: value}), policy())
    assert error.value.code == code


def test_selects_one_allowed_testnet_requirement_without_inventing_or_mixing_terms():
    value = challenge()
    mainnet = deepcopy(value["accepts"][0])
    mainnet.update(network="eip155:8453", payTo="0x" + "ff" * 20)
    value["accepts"].insert(0, mainnet)
    action = validate_quote(request(), value, policy())
    assert action["payment_requirements"] == value["accepts"][1]


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(x402Version=1),
    lambda c: c.update(x402Version=True),
    lambda c: c.update(accepts=[]),
    lambda c: c.update(accepts=[None]),
    lambda c: c.update(accepts=c["accepts"] * 17),
    lambda c: c["resource"].update(url=URL + "&changed=true"),
    lambda c: c["resource"].update(description="x" * 17000),
    lambda c: c["accepts"][0]["extra"].update(unsafe=float("nan")),
])
def test_malformed_or_changed_resource_challenges_fail_closed(mutate):
    value = challenge()
    mutate(value)
    with pytest.raises(Denied):
        validate_quote(request(), value, policy())


def test_method_headers_body_and_disabled_feature_cannot_be_smuggled_into_request():
    for addition in ({"method": "POST"}, {"headers": {}}, {"body": "data"}):
        with pytest.raises(Denied):
            validate_request({**request(), **addition}, policy())
    with pytest.raises(Denied) as error:
        validate_request(request(), X402Policy())
    assert error.value.code == "X402_DISABLED"


def valid_settlement():
    return {
        "network": BASE_SEPOLIA_NETWORK,
        "transaction": "0x" + "ab" * 32,
        "payer": "0x" + "56" * 20,
        "asset": BASE_SEPOLIA_USDC,
        "pay_to": PAYEE,
        "amount_atomic": "10001",
        "verified": True,
        "authorization_verified": True,
        "block_number": 123,
    }


def test_verified_settlement_requires_exact_receipt_tuple_and_actual_authorization():
    action = validate_quote(request(), challenge(), policy())
    assert settlement_verified(valid_settlement(), action)
    for change in (
        {"verified": False}, {"verified": 1}, {"authorization_verified": False},
        {"network": "eip155:8453"}, {"asset": "0x" + "ff" * 20},
        {"pay_to": "0x" + "34" * 20}, {"amount_atomic": "10000"},
        {"amount_atomic": 10001}, {"block_number": True}, {"block_number": 0},
        {"transaction": "a" * 64}, {"payer": "0x" + "00" * 20},
    ):
        assert not settlement_verified({**valid_settlement(), **change}, action)

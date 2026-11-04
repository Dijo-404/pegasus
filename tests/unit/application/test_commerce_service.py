"""Use cases run with injected ports and no framework, database or signing secret."""

import time

import pytest

from pegasus.application.commerce_service import CommerceService
from pegasus.domain.commerce_policy import CommercePolicy
from pegasus.domain.exceptions import Denied


class MemoryRepository:
    def __init__(self):
        self.intents = {}
        self.events = []

    def insert_intent(self, intent):
        self.intents[intent["id"]] = intent

    def intent(self, intent_id):
        return self.intents[intent_id]

    def approve(self, intent_id, expected_digest, ttl):
        intent = self.intents[intent_id]
        assert intent["digest"] == expected_digest
        intent["status"] = "AUTHORIZED"
        return "fixture-grant-id", min(intent["expires_at"], int(time.time()) + ttl)


class Catalog:
    calls = 0

    async def details(self, product_id):
        self.calls += 1
        return {
            "product_id": product_id,
            "countries": ["IN"],
            "in_stock": True,
            "payment_methods": ["lightning"],
            "recipient_type": "none",
            "packages": [{"package_value": "10", "payment_price": "0.11", "payment_currency": "USD"}],
        }


class RecordingGrantAuthority:
    claims = None

    def sign(self, claims):
        self.claims = claims
        return "fixture-signed-grant"


def setup_service():
    policy = CommercePolicy(
        max_purchase_minor=500,
        max_daily_minor=1000,
        allowed_products=frozenset({"demo-product"}),
        allowed_countries=frozenset({"IN"}),
        allowed_emails=frozenset({"owner@example.invalid"}),
        allowed_recipients=frozenset(),
        quote_ttl_seconds=300,
        grant_ttl_seconds=90,
    )
    repository, provider, grants = MemoryRepository(), Catalog(), RecordingGrantAuthority()
    return CommerceService(policy, repository, provider, grants), repository, provider, grants


def proposal(**changes):
    return {
        "product_id": "demo-product",
        "package_value": "10",
        "country": "IN",
        "recipient": "",
        "email": "owner@example.invalid",
        "payment_method": "lightning",
        "max_total_minor": 11,
        **changes,
    }


async def test_purchase_use_case_uses_repository_and_grant_ports():
    service, repository, provider, grants = setup_service()
    intent = await service.propose(proposal())
    approval = service.approve(intent["id"], intent["digest"])

    assert provider.calls == 1
    assert repository.intent(intent["id"])["status"] == "AUTHORIZED"
    assert approval["grant"] == "fixture-signed-grant"
    assert grants.claims["digest"] == intent["digest"]
    assert grants.claims["action"] == "bitrefill.create_invoice"
    assert grants.claims["max_total_minor"] == 11


async def test_allowlist_rejection_precedes_external_catalog_access():
    service, repository, provider, grants = setup_service()
    with pytest.raises(Denied) as error:
        await service.propose(proposal(product_id="unapproved-product"))

    assert error.value.code == "PRODUCT_DENIED"
    assert provider.calls == 0
    assert repository.intents == {}
    assert grants.claims is None

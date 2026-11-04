"""Explicit doubles exercise authority order; no SDK signing or live payments."""

import asyncio
from copy import deepcopy
import time

import pytest

from pegasus.application.x402_service import X402Service
from pegasus.domain.authorization_policy import approval_expiry, validate_daily_budget, validate_reservation
from pegasus.domain.exceptions import Denied
from pegasus.domain.x402_policy import BASE_SEPOLIA_NETWORK, BASE_SEPOLIA_USDC, X402Policy

URL = "https://api.example.com/private/data"
PAYEE = "0x" + "12" * 20


class MemoryRepository:
    def __init__(self, events):
        self.intents, self.grants, self.reservations, self.events = {}, {}, {}, events

    def insert_intent(self, intent):
        self.intents[intent["id"]] = deepcopy(intent)

    def intent(self, intent_id):
        return deepcopy(self.intents[intent_id])

    def list_intents(self):
        return [deepcopy(intent) for intent in self.intents.values()]

    def save_intent(self, intent):
        self.intents[intent["id"]] = deepcopy(intent)

    def approve(self, intent_id, expected_digest, ttl):
        intent = self.intents[intent_id]
        expires = approval_expiry(intent, expected_digest, int(time.time()), ttl)
        grant = {
            "id": "grant-" + intent_id, "intent_id": intent_id, "digest": expected_digest,
            "expires_at": expires, "consumed_at": None,
        }
        self.grants[grant["id"]] = grant
        intent["status"] = "AUTHORIZED"
        return grant["id"], expires

    def reserve(self, intent_id, claims, day, daily_cap):
        intent, grant = self.intents[intent_id], self.grants[claims["jti"]]
        validate_reservation(intent, grant, int(time.time()))
        amount = intent["action"]["max_total_minor"]
        validate_daily_budget(sum(self.reservations.values()), amount, daily_cap)
        self.reservations[intent_id] = amount
        grant["consumed_at"] = int(time.time())
        intent["status"] = "EXECUTING"
        self.events.append("reserve")
        return deepcopy(intent)

    def event(self, intent_id, action, reason):
        self.events.append((intent_id, action, reason))

    def audit(self, intent_id):
        return [event for event in self.events if isinstance(event, tuple) and event[0] == intent_id]


class Grants:
    def __init__(self):
        self.claims = {}

    def sign(self, claims):
        token = "token-" + claims["jti"]
        self.claims[token] = deepcopy(claims)
        return token

    def verify(self, token):
        return deepcopy(self.claims[token])


class Provider:
    def __init__(self, events):
        self.events = events
        self.challenge = {
            "x402Version": 2,
            "resource": {"url": URL, "description": "Protected API", "mimeType": "application/json"},
            "accepts": [{
                "scheme": "exact", "network": BASE_SEPOLIA_NETWORK, "asset": BASE_SEPOLIA_USDC,
                "payTo": PAYEE, "amount": "10001", "maxTimeoutSeconds": 300,
                "extra": {"name": "USDC", "version": "2"},
            }],
        }
        self.outcome = None
        self.calls = 0
        self.discoveries = 0
        self.failure = None

    async def discover(self, url):
        assert url == URL
        self.events.append("discover")
        self.discoveries += 1
        await asyncio.sleep(0)
        return deepcopy(self.challenge)

    async def pay(self, action):
        self.events.append("pay")
        self.calls += 1
        await asyncio.sleep(0)
        if self.failure:
            raise self.failure
        return self.outcome if self.outcome is not None else {
            "status": "SUCCEEDED", "result": {"content_type": "application/json", "body": {"data": "value"}},
            "settlement": {
                "network": BASE_SEPOLIA_NETWORK, "asset": BASE_SEPOLIA_USDC, "pay_to": PAYEE,
                "amount_atomic": action["amount_atomic"], "payer": "0x" + "56" * 20,
                "transaction": "0x" + "ab" * 32, "block_number": 123,
                "verified": True, "authorization_verified": True,
            },
        }


def setup_service(**policy_changes):
    events = []
    repository, provider, grants = MemoryRepository(events), Provider(events), Grants()
    policy = X402Policy(**{
        "enabled": True, "allowed_origins": frozenset({"https://api.example.com"}),
        "allowed_payees": frozenset({PAYEE}), **policy_changes,
    })
    return X402Service(policy, repository, provider, grants), repository, provider, grants, events


async def authorized(service, maximum=2):
    intent = await service.propose({"url": URL, "max_total_minor": maximum})
    return intent, service.approve(intent["id"], intent["digest"])["grant"]


async def test_exact_owner_grant_reserves_ceiling_before_one_payment_and_verified_result():
    service, repository, provider, grants, events = setup_service()
    intent, token = await authorized(service)
    claims = grants.claims[token]
    assert claims["action"] == "x402.pay_request"
    assert claims["digest"] == intent["digest"]
    assert claims["max_total_minor"] == 2
    result = await service.execute(intent["id"], token)
    assert result["status"] == "SUCCEEDED"
    assert result["settlement"]["authorization_verified"] is True
    assert result["result"]["body"] == {"data": "value"}
    assert events[:4] == ["discover", "discover", "reserve", "pay"]
    assert repository.reservations == {intent["id"]: 2}
    with pytest.raises(Denied):
        await service.execute(intent["id"], token)
    assert provider.calls == 1
    assert provider.discoveries == 2


async def test_disabled_origin_and_cap_denials_precede_external_discovery():
    for changes, request in (
        ({"enabled": False}, {"url": URL, "max_total_minor": 2}),
        ({}, {"url": "https://unapproved.example.com/data", "max_total_minor": 2}),
        ({}, {"url": URL, "max_total_minor": True}),
        ({}, {"url": URL, "max_total_minor": 501}),
    ):
        service, repository, provider, _, _ = setup_service(**changes)
        with pytest.raises(Denied):
            await service.propose(request)
        assert provider.discoveries == 0
        assert not repository.intents


@pytest.mark.parametrize("change", ["amount", "resource", "extra", "payee", "mainnet"])
async def test_rediscovered_challenge_must_match_entire_approved_action_before_reservation(change):
    service, repository, provider, _, _ = setup_service()
    intent, token = await authorized(service)
    requirement = provider.challenge["accepts"][0]
    if change == "amount":
        requirement["amount"] = "10002"  # Still under ceiling; exact approval nevertheless changed.
    elif change == "resource":
        provider.challenge["resource"]["description"] = "Different resource metadata"
    elif change == "extra":
        requirement["extra"]["version"] = "3"
    elif change == "payee":
        requirement["payTo"] = "0x" + "34" * 20
    else:
        requirement["network"] = "eip155:8453"
    with pytest.raises(Denied):
        await service.execute(intent["id"], token)
    assert not repository.reservations
    assert provider.calls == 0


async def test_distinct_grant_and_immutable_action_cannot_be_substituted():
    service, repository, provider, grants, _ = setup_service()
    intent, token = await authorized(service)
    original = deepcopy(grants.claims[token])
    for change in (
        {"action": "bitrefill.create_invoice"}, {"intent_id": "xi_other"}, {"digest": "f" * 64},
        {"currency": "TAZ"}, {"max_total_minor": True}, {"max_total_minor": 3},
    ):
        grants.claims[token] = {**original, **change}
        with pytest.raises(Denied) as error:
            await service.execute(intent["id"], token)
        assert error.value.code == "INTENT_MISMATCH"
    grants.claims[token] = original
    repository.intents[intent["id"]]["action"]["amount_atomic"] = "1"
    with pytest.raises(Denied):
        await service.execute(intent["id"], token)
    assert provider.calls == 0
    assert not repository.reservations


async def test_other_rail_is_not_listed_read_approved_executed_or_audited():
    service, repository, provider, grants, _ = setup_service()
    intent, token = await authorized(service)
    commerce = {**deepcopy(intent), "id": "pi_other", "kind": "commerce"}
    repository.intents[commerce["id"]] = commerce
    assert [value["id"] for value in service.list_intents()] == [intent["id"]]
    for operation in (
        lambda: service.get_intent(commerce["id"]),
        lambda: service.get_audit(commerce["id"]),
        lambda: service.approve(commerce["id"], commerce["digest"]),
    ):
        with pytest.raises(Denied) as error:
            operation()
        assert error.value.code == "NOT_FOUND"
    assert repository.intents[commerce["id"]]["status"] == "AWAITING_APPROVAL"
    with pytest.raises(Denied):
        await service.execute(commerce["id"], token)
    assert len(grants.claims) == 1
    assert provider.calls == 0


@pytest.mark.parametrize("outcome", [
    {"status": "SUCCEEDED", "result": {"body": "HTTP 200 only"}, "settlement": None},
    {"status": "UNCERTAIN", "reason": "potential secret upstream payload"},
    {"status": "DELIVERED", "result": "merchant says paid"},
    None,
])
async def test_unverified_or_failed_payment_is_uncertain_with_authority_and_budget_retained(outcome):
    service, repository, provider, _, _ = setup_service()
    intent, token = await authorized(service)
    if outcome is None:
        provider.failure = RuntimeError("secret signature must not leak")
    else:
        provider.outcome = outcome
    result = await service.execute(intent["id"], token)
    assert result["status"] == "UNCERTAIN"
    assert result["reason"] == "PAYMENT_RESULT_UNCERTAIN"
    assert result["result"] is None and result["settlement"] is None
    assert repository.reservations == {intent["id"]: 2}
    assert all(grant["consumed_at"] is not None for grant in repository.grants.values())
    with pytest.raises(Denied):
        await service.execute(intent["id"], token)
    assert provider.calls == 1


async def test_shared_daily_budget_denial_happens_before_signing():
    service, repository, provider, _, _ = setup_service(max_daily_minor=5)
    repository.reservations["pi_existing_commerce"] = 4
    intent, token = await authorized(service)
    with pytest.raises(Denied) as error:
        await service.execute(intent["id"], token)
    assert error.value.code == "DAILY_CAP"
    assert provider.calls == 0
    assert repository.reservations == {"pi_existing_commerce": 4}


async def test_concurrent_attempts_sign_at_most_once():
    service, repository, provider, _, _ = setup_service()
    intent, token = await authorized(service)
    results = await asyncio.gather(
        service.execute(intent["id"], token), service.execute(intent["id"], token), return_exceptions=True
    )
    assert sum(isinstance(result, Denied) for result in results) == 1
    assert provider.calls == 1
    assert repository.reservations == {intent["id"]: 2}


async def test_expired_quote_is_denied_without_reservation_or_payment():
    service, repository, provider, _, _ = setup_service()
    intent, token = await authorized(service)
    repository.intents[intent["id"]]["expires_at"] = int(time.time()) - 1
    with pytest.raises(Denied) as error:
        await service.execute(intent["id"], token)
    assert error.value.code == "GRANT_EXPIRED"
    assert provider.calls == 0
    assert not repository.reservations


async def test_cancellation_after_reservation_records_uncertainty_before_propagating():
    service, repository, provider, _, _ = setup_service()
    intent, token = await authorized(service)
    provider.failure = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.execute(intent["id"], token)
    assert repository.intent(intent["id"])["status"] == "UNCERTAIN"
    assert repository.reservations == {intent["id"]: 2}
    assert provider.calls == 1


async def test_provider_cannot_mutate_the_approved_action_to_validate_substituted_receipt():
    service, repository, provider, _, _ = setup_service()
    intent, token = await authorized(service)
    original_pay = provider.pay

    async def substituting_pay(action):
        action["amount_atomic"] = "1"
        return await original_pay(action)

    provider.pay = substituting_pay
    result = await service.execute(intent["id"], token)
    assert result["status"] == "UNCERTAIN"
    assert result["action"] == intent["action"]
    assert repository.intent(intent["id"])["action"]["amount_atomic"] == "10001"
    assert provider.calls == 1

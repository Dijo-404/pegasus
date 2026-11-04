"""Explicit doubles exercise owner authority and shared outbound budget, not live settlement."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from pegasus.bootstrap import create_app
from pegasus.domain.exceptions import Denied
from pegasus.domain.x402_policy import BASE_SEPOLIA_NETWORK, BASE_SEPOLIA_USDC
from pegasus.infrastructure.security.hmac_grant_authority import HmacGrantAuthority
from pegasus.infrastructure.settings import Settings


URL = "https://api.example.com/report"
PAYEE = "0x" + "1" * 40
PAYER = "0x" + "2" * 40


class FixtureX402Provider:
    """No network or signer: these responses are test fixtures only."""

    def __init__(self):
        self.discoveries = 0
        self.payments = 0
        self.fail = False
        self.before_pay = None
        self.challenge = {
            "x402Version": 2,
            "resource": {"url": URL, "description": "Fixture report", "mimeType": "application/json"},
            "accepts": [{
                "scheme": "exact", "network": BASE_SEPOLIA_NETWORK,
                "asset": BASE_SEPOLIA_USDC, "payTo": PAYEE, "amount": "10000",
                "maxTimeoutSeconds": 60, "extra": {"name": "USDC", "version": "2"},
            }],
        }

    async def discover(self, url):
        self.discoveries += 1
        return deepcopy(self.challenge)

    async def pay(self, action):
        self.payments += 1
        if self.before_pay:
            self.before_pay()
        await asyncio.sleep(0.01)
        if self.fail:
            raise RuntimeError("signature-and-key-canary-must-not-escape")
        return {
            "status": "SUCCEEDED",
            "result": {"content_type": "application/json", "body": {"source": "explicit test fixture"}},
            "settlement": {
                "verified": True, "authorization_verified": True, "network": BASE_SEPOLIA_NETWORK,
                "asset": BASE_SEPOLIA_USDC, "payer": PAYER, "pay_to": PAYEE,
                "amount_atomic": action["amount_atomic"], "transaction": "0x" + "3" * 64,
                "block_number": 123,
            },
        }


@pytest.fixture
def gateway(tmp_path):
    settings = Settings(
        owner_token="o" * 48, agent_token="a" * 48, grant_secret="s" * 48,
        data_key=Fernet.generate_key().decode(), database_path=str(tmp_path / "gateway.db"),
        x402_enabled=True, x402_allowed_origins=frozenset({"https://api.example.com"}),
        x402_allowed_payees=frozenset({PAYEE}),
    )
    provider = FixtureX402Provider()
    app = create_app(settings=settings, x402=provider)
    with TestClient(app) as client:
        yield settings, provider, app, client


def auth(settings, owner=False):
    return {"Authorization": "Bearer " + (settings.owner_token if owner else settings.agent_token)}


def propose_and_approve(settings, client, ceiling=1):
    proposal = client.post("/api/x402/intents", headers=auth(settings),
                           json={"url": URL, "max_total_minor": ceiling})
    assert proposal.status_code == 200, proposal.text
    intent = proposal.json()
    approval = client.post(f"/api/x402/intents/{intent['id']}/approve", headers=auth(settings, True),
                           json={"digest": intent["digest"]})
    assert approval.status_code == 200, approval.text
    return intent, approval.json()["grant"]


def test_authentication_exact_owner_approval_and_single_attempt(gateway):
    settings, provider, app, client = gateway
    assert client.post("/api/x402/intents", json={"url": URL, "max_total_minor": 1}).status_code == 401
    proposed = client.post("/api/x402/intents", headers=auth(settings),
                           json={"url": URL, "max_total_minor": 1}).json()
    assert provider.payments == 0
    path = f"/api/x402/intents/{proposed['id']}"
    assert client.post(path + "/approve", headers=auth(settings),
                       json={"digest": proposed["digest"]}).status_code == 403
    assert client.post(path + "/approve", headers=auth(settings, True),
                       json={"digest": "0" * 64}).status_code == 409
    grant = client.post(path + "/approve", headers=auth(settings, True),
                        json={"digest": proposed["digest"]}).json()["grant"]

    def assert_reserved_before_signing():
        with app.state.x402.repository.connect() as db:
            assert db.execute("SELECT SUM(total_minor) FROM reservations").fetchone()[0] == 1
            assert db.execute("SELECT consumed_at FROM grants").fetchone()[0] is not None
    provider.before_pay = assert_reserved_before_signing
    response = client.post(path + "/execute", headers=auth(settings), json={"grant": grant})
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert response.json()["result"]["body"]["source"] == "explicit test fixture"
    assert provider.payments == 1
    assert client.post(path + "/execute", headers=auth(settings), json={"grant": grant}).status_code == 409
    assert provider.payments == 1
    assert client.get(path, headers=auth(settings)).json()["status"] == "SUCCEEDED"


def test_changed_challenge_does_not_reserve_or_sign(gateway):
    settings, provider, app, client = gateway
    intent, grant = propose_and_approve(settings, client)
    provider.challenge["accepts"][0]["amount"] = "9999"
    response = client.post(f"/api/x402/intents/{intent['id']}/execute", headers=auth(settings),
                           json={"grant": grant})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QUOTE_CHANGED"
    assert provider.payments == 0
    with app.state.x402.repository.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0


def test_ambiguous_payment_retains_budget_and_never_repeats(gateway):
    settings, provider, app, client = gateway
    intent, grant = propose_and_approve(settings, client, ceiling=2)
    provider.fail = True
    path = f"/api/x402/intents/{intent['id']}"
    response = client.post(path + "/execute", headers=auth(settings), json={"grant": grant})
    assert response.status_code == 200
    assert response.json()["status"] == "UNCERTAIN"
    assert response.json()["result"] is None
    assert "canary" not in response.text
    assert client.post(path + "/execute", headers=auth(settings), json={"grant": grant}).status_code == 409
    assert provider.payments == 1
    with app.state.x402.repository.connect() as db:
        assert db.execute("SELECT SUM(total_minor) FROM reservations").fetchone()[0] == 2


def test_other_rail_cannot_read_approve_or_execute_api_intent(gateway):
    settings, provider, app, client = gateway
    intent, grant = propose_and_approve(settings, client)
    for suffix in ("", "/audit"):
        assert client.get(f"/api/intents/{intent['id']}" + suffix,
                          headers=auth(settings)).status_code == 404
    assert client.post(f"/api/intents/{intent['id']}/approve", headers=auth(settings, True),
                       json={"digest": intent["digest"]}).status_code == 404
    assert client.post(f"/api/intents/{intent['id']}/execute", headers=auth(settings),
                       json={"grant": grant}).status_code == 409
    assert client.get("/api/intents", headers=auth(settings)).json() == {"intents": []}
    assert provider.payments == 0
    with pytest.raises(Denied):
        HmacGrantAuthority(settings.grant_secret).verify(grant)


def test_shared_budget_and_restart_do_not_reset_reservation(gateway):
    settings, provider, app, client = gateway
    service = app.state.x402
    # Existing commerce reservations occupy the same exact USD-cent ledger.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    with service.repository.transaction() as db:
        db.execute("INSERT INTO reservations VALUES(?,?,?)", ("pi_existing", day, 1000))
    intent, grant = propose_and_approve(settings, client)
    response = client.post(f"/api/x402/intents/{intent['id']}/execute", headers=auth(settings),
                           json={"grant": grant})
    assert response.json()["error"]["code"] == "DAILY_CAP"
    assert provider.payments == 0
    # An interrupted reserved call becomes uncertain at startup; it is not resent.
    with service.repository.transaction() as db:
        db.execute("DELETE FROM reservations")
    claims = service.grants.verify(grant)
    service.repository.reserve(intent["id"], claims, day, 1000)
    restarted = create_app(settings=settings, x402=provider)
    with TestClient(restarted) as again:
        state = again.get(f"/api/x402/intents/{intent['id']}", headers=auth(settings)).json()
        assert state["status"] == "UNCERTAIN"
        assert state["result"] is None
        assert again.post(f"/api/x402/intents/{intent['id']}/execute", headers=auth(settings),
                          json={"grant": grant}).status_code == 409
    assert provider.payments == 0


def test_config_never_exposes_key_path_and_disabled_feature_does_not_sign(gateway):
    settings, provider, app, client = gateway
    config = client.get("/api/config").json()
    assert config["x402"]["network"] == BASE_SEPOLIA_NETWORK
    assert "private_key" not in json.dumps(config)
    assert "x402-payer" not in json.dumps(config)
    disabled = create_app(settings=replace(settings, x402_enabled=False), x402=provider)
    with TestClient(disabled) as other:
        result = other.post("/api/x402/intents", headers=auth(settings),
                            json={"url": URL, "max_total_minor": 1})
        assert result.status_code == 503
    assert provider.payments == 0


def test_unsafe_and_invalid_proposals_fail_before_discovery(gateway):
    settings, provider, app, client = gateway
    for value in [{"url": "http://127.0.0.1/private", "max_total_minor": 1},
                  {"url": URL, "max_total_minor": 501},
                  {"url": URL, "max_total_minor": True},
                  {"url": URL, "max_total_minor": 1, "private_key": "secret-canary"}]:
        response = client.post("/api/x402/intents", headers=auth(settings), json=value)
        assert response.status_code in (409, 422)
        assert "secret-canary" not in response.text
    assert provider.discoveries == provider.payments == 0


def test_concurrent_reservations_across_rails_cannot_double_the_daily_cap(gateway):
    settings, provider, app, client = gateway
    repository = app.state.x402.repository
    claims = []
    for number, kind in enumerate(("commerce", "x402")):
        value = {
            "id": f"{'pi' if kind == 'commerce' else 'xi'}_{number:032x}",
            "kind": kind, "action": {"max_total_minor": 500, "currency": "USD"},
            "digest": "d" * 64, "status": "AWAITING_APPROVAL",
            "created_at": int(time.time()), "expires_at": int(time.time()) + 300,
        }
        repository.insert_intent(value)
        grant, _ = repository.approve(value["id"], value["digest"], 90)
        claims.append((value["id"], {"jti": grant}))

    def reserve(pair):
        try:
            repository.reserve(pair[0], pair[1], "2026-11-04", 500)
            return "reserved"
        except Denied as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, claims)) == ["DAILY_CAP", "reserved"]
    with repository.connect() as db:
        assert db.execute("SELECT SUM(total_minor) FROM reservations").fetchone()[0] == 500
        assert db.execute("SELECT COUNT(*) FROM grants WHERE consumed_at IS NOT NULL").fetchone()[0] == 1
    assert provider.payments == 0


def test_disabled_bootstrap_needs_no_optional_sdk_or_key(gateway, monkeypatch):
    import builtins

    settings, provider, app, client = gateway
    original_import = builtins.__import__
    attempts = []

    def without_wallet_packages(name, *args, **kwargs):
        if name == "x402" or name.startswith("x402.") or name == "eth_account":
            attempts.append(name)
            raise ImportError("Optional wallet packages deliberately unavailable in this test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_wallet_packages)
    disabled = create_app(settings=replace(settings, x402_enabled=False))
    with TestClient(disabled) as other:
        assert other.get("/health").json()["status"] == "ok"
        assert other.get("/api/config").json()["x402"]["configured"] is False
    assert attempts == []

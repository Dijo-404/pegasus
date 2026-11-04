"""Offline protocol, network-policy and SDK tests; no live payment is evidence here."""

import asyncio
import base64
import builtins
import copy
import json
import os
import time

import httpx
import pytest

import pegasus.infrastructure.providers.x402_client as adapter
from pegasus.infrastructure.providers.x402_client import (
    AUTHORIZATION_USED_TOPIC,
    BASE_SEPOLIA_NETWORK,
    BASE_SEPOLIA_USDC,
    TRANSFER_TOPIC,
    PublicHTTPSClient,
    X402Client,
    X402Error,
    validate_public_https_url,
    verify_receipt,
)

URL = "https://merchant.example.com/data?format=json"
RPC = "https://rpc.example.com/"
PAYER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
NONCE = "0x" + "33" * 32
TXID = "0x" + "55" * 32
BLOCK = "0x" + "66" * 32
PUBLIC_IP = "93.184.216.34"


def encoded(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


def action(**changes):
    result = {
        "type": "x402.pay_request",
        "method": "GET",
        "url": URL,
        "scheme": "exact",
        "network": BASE_SEPOLIA_NETWORK,
        "asset": BASE_SEPOLIA_USDC,
        "pay_to": PAYEE,
        "amount_atomic": "250000",
        "total_minor": 25,
        "max_total_minor": 50,
        "currency": "USD",
        "max_timeout_seconds": 60,
        "resource": {"url": URL, "description": "Offline fixture", "merchantMetadata": {"revision": 1}},
    }
    result.update(changes)
    result["payment_requirements"] = {
        "scheme": result["scheme"],
        "network": result["network"],
        "asset": result["asset"],
        "payTo": result["pay_to"],
        "amount": result["amount_atomic"],
        "maxTimeoutSeconds": result["max_timeout_seconds"],
        "extra": {"name": "USDC", "version": "2"},
        "merchantRevision": "approved-exactly",
    }
    return result


def payload(approved=None):
    approved = approved or action()
    return {
        "x402Version": 2,
        "accepted": copy.deepcopy(approved["payment_requirements"]),
        "resource": copy.deepcopy(approved["resource"]),
        "payload": {
            "authorization": {
                "from": PAYER,
                "to": approved["pay_to"],
                "value": approved["amount_atomic"],
                "validAfter": "0",
                "validBefore": str(int(time.time()) + approved["max_timeout_seconds"]),
                "nonce": NONCE,
            },
            "signature": "0x" + "44" * 65,
        },
    }


def topic(address):
    return "0x" + "0" * 24 + address[2:].lower()


def receipt(approved=None, nonce=NONCE):
    approved = approved or action()
    common = {
        "address": BASE_SEPOLIA_USDC,
        "removed": False,
        "transactionHash": TXID,
        "blockHash": BLOCK,
        "blockNumber": "0x10",
    }
    return {
        "transactionHash": TXID,
        "status": "0x1",
        "blockHash": BLOCK,
        "blockNumber": "0x10",
        "logs": [
            {
                **common,
                "topics": [TRANSFER_TOPIC, topic(PAYER), topic(PAYEE)],
                "data": "0x" + f"{int(approved['amount_atomic']):064x}",
            },
            {**common, "topics": [AUTHORIZATION_USED_TOPIC, topic(PAYER), nonce], "data": "0x"},
        ],
    }


async def public_resolver(host):
    return [PUBLIC_IP]


class FixtureServer:
    def __init__(self, *, paid_status=200, proof=None, settlement=True, body=None, chain=84532):
        self.calls = []
        self.paid = []
        self.paid_status = paid_status
        self.proof = proof
        self.settlement = settlement
        self.body = body
        self.chain = chain

    def __call__(self, request):
        self.calls.append(request)
        assert request.url.host == PUBLIC_IP
        assert request.extensions["sni_hostname"] == request.headers["host"]
        assert request.headers["accept-encoding"] == "identity"
        if request.method == "POST":
            assert request.headers["host"] == "rpc.example.com"
            rpc = json.loads(request.content)
            if rpc["method"] == "eth_chainId":
                result = hex(self.chain)
            else:
                assert rpc["method"] == "eth_getTransactionReceipt"
                assert rpc["params"] == [TXID]
                nonce = self.paid[-1]["payload"]["authorization"]["nonce"]
                amount = self.paid[-1]["payload"]["authorization"]["value"]
                result = (
                    receipt(action(amount_atomic=amount), nonce=nonce) if self.proof is None else self.proof
                )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})
        assert request.headers["host"] == "merchant.example.com"
        if "payment-signature" not in request.headers:
            approved = action()
            challenge = {
                "x402Version": 2,
                "accepts": [approved["payment_requirements"]],
                "resource": approved["resource"],
            }
            return httpx.Response(402, headers={"PAYMENT-REQUIRED": encoded(challenge)}, json={})
        self.paid.append(json.loads(base64.b64decode(request.headers["payment-signature"])))
        headers = {}
        if self.settlement:
            headers["PAYMENT-RESPONSE"] = encoded(
                {
                    "success": True,
                    "network": BASE_SEPOLIA_NETWORK,
                    "transaction": TXID,
                    "payer": PAYER,
                }
            )
        if self.paid_status == 302:
            headers["location"] = "https://other.example.com/steal"
        return httpx.Response(self.paid_status, headers=headers, json=self.body or {"resource": "fixture"})


def client(server, monkeypatch=None, **options):
    result = X402Client(
        "/not-read/demo-key", RPC, transport=httpx.MockTransport(server), resolver=public_resolver, **options
    )
    if monkeypatch is not None:

        async def create_payload(approved):
            return payload(approved), PAYER

        monkeypatch.setattr(result, "_create_payload", create_payload)
    return result


@pytest.mark.parametrize(
    "url",
    [
        "http://merchant.example.com/",
        "HTTPS://merchant.example.com/",
        "https://localhost/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://merchant.example.com:8443/",
        "https://user:secret@merchant.example.com/",
        "https://merchant.example.com/#secret",
        "https://merchant.example.com/\nheader",
        "https://merchant.example.com\\@localhost/",
        "https://éxample.com/",
        "https://merchant.example.com./",
    ],
)
def test_public_url_policy_rejects_unsafe_destinations(url):
    with pytest.raises(X402Error):
        validate_public_https_url(url)


@pytest.mark.asyncio
async def test_unsigned_discovery_needs_no_sdk_key_or_signature(monkeypatch):
    def forbidden(*args):
        pytest.fail("Discovery must not load a signing key")

    monkeypatch.setattr(adapter, "_load_signer", forbidden)
    server = FixtureServer()
    discovered = await client(server).discover(URL)
    assert discovered["x402Version"] == 2
    assert len(server.calls) == 1 and not server.paid
    assert "payment-signature" not in server.calls[0].headers
    assert "authorization" not in server.calls[0].headers


@pytest.mark.asyncio
async def test_disabled_adapter_and_unsigned_discovery_work_when_optional_imports_are_unavailable(
    monkeypatch,
):
    actual_import = builtins.__import__

    def without_optional(name, *args, **kwargs):
        if name.split(".")[0] in {"x402", "eth_account", "web3"}:
            raise ImportError("Optional SDK intentionally unavailable in this offline test")
        return actual_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_optional)
    candidate = client(FixtureServer())
    assert (await candidate.discover(URL))["x402Version"] == 2
    outcome = await candidate.pay(action())
    assert outcome["status"] == "UNCERTAIN" and outcome["reason"] == "X402_SDK_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fe80::1"],
        ["::ffff:127.0.0.1"],
        ["224.0.0.1"],
        [PUBLIC_IP, "192.168.1.2"],
        [],
    ],
)
async def test_all_dns_answers_must_be_public_before_request(addresses):
    calls = []

    async def resolver(host):
        return addresses

    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
    http = PublicHTTPSClient(resolver=resolver, transport=transport)
    with pytest.raises(X402Error):
        await http.request("GET", URL)
    assert calls == []


@pytest.mark.asyncio
async def test_dns_is_resolved_once_and_host_sni_are_pinned(monkeypatch):
    hosts = []

    async def resolver(host):
        hosts.append(host)
        return [PUBLIC_IP]

    def handler(request):
        assert request.url.host == PUBLIC_IP
        assert request.headers["host"] == "merchant.example.com"
        assert request.extensions["sni_hostname"] == "merchant.example.com"
        return httpx.Response(200, text="ok")

    # Proxy settings must not cause another HTTP destination or DNS lookup.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    http = PublicHTTPSClient(resolver=resolver, transport=httpx.MockTransport(handler))
    assert (await http.request("GET", URL)).text == "ok"
    assert hosts == ["merchant.example.com"]


@pytest.mark.asyncio
async def test_discovery_rejects_redirects_oversized_duplicate_and_v1_headers():
    bad_responses = [
        httpx.Response(302, headers={"location": "https://other.example.com"}),
        httpx.Response(200),
        httpx.Response(402, headers={"PAYMENT-REQUIRED": "not base64"}),
        httpx.Response(402, headers=[("PAYMENT-REQUIRED", encoded({})), ("PAYMENT-REQUIRED", encoded({}))]),
        httpx.Response(402, headers={"PAYMENT-REQUIRED": encoded({"x402Version": 1, "accepts": [{}]})}),
        httpx.Response(402, headers={"PAYMENT-REQUIRED": "a" * (adapter.MAX_PAYMENT_HEADER_BYTES + 1)}),
        httpx.Response(402, content=b"x" * (adapter.MAX_BODY_BYTES + 1)),
        httpx.Response(402, headers={"content-encoding": "br"}),
    ]
    for response in bad_responses:
        calls = []

        def handler(request):
            calls.append(request)
            return response

        with pytest.raises(X402Error):
            await client(handler).discover(URL)
        assert len(calls) == 1


def test_receipt_binds_transfer_and_authorization_nonce():
    assert verify_receipt(receipt(), TXID, action(), PAYER, NONCE) == 16
    old_receipt = receipt(nonce="0x" + "77" * 32)
    with pytest.raises(X402Error):
        verify_receipt(old_receipt, TXID, action(), PAYER, NONCE)


@pytest.mark.parametrize(
    "change",
    [
        "failed",
        "pending",
        "wrong_transaction",
        "wrong_block",
        "wrong_token",
        "wrong_payer",
        "wrong_payee",
        "short_amount",
        "wrong_authorizer",
        "removed",
        "missing_authorization",
        "missing_transfer",
    ],
)
def test_incomplete_or_substituted_rpc_proof_never_succeeds(change):
    proof = receipt()
    if change == "failed":
        proof["status"] = "0x0"
    elif change == "pending":
        proof["blockNumber"] = "0x0"
    elif change == "wrong_transaction":
        proof["transactionHash"] = "0x" + "77" * 32
    elif change == "wrong_block":
        proof["logs"][0]["blockHash"] = "0x" + "77" * 32
    elif change == "wrong_token":
        for log in proof["logs"]:
            log["address"] = PAYEE
    elif change == "wrong_payer":
        proof["logs"][0]["topics"][1] = topic(PAYEE)
    elif change == "wrong_payee":
        proof["logs"][0]["topics"][2] = topic(PAYER)
    elif change == "short_amount":
        proof["logs"][0]["data"] = "0x" + f"{249999:064x}"
    elif change == "wrong_authorizer":
        proof["logs"][1]["topics"][1] = topic(PAYEE)
    elif change == "removed":
        proof["logs"][0]["removed"] = True
    elif change == "missing_authorization":
        proof["logs"].pop()
    elif change == "missing_transfer":
        proof["logs"].pop(0)
    with pytest.raises(X402Error):
        verify_receipt(proof, TXID, action(), PAYER, NONCE)


@pytest.mark.asyncio
async def test_exactly_one_paid_get_and_independent_receipt_are_required(monkeypatch):
    server = FixtureServer()
    outcome = await client(server, monkeypatch).pay(action())
    assert outcome["status"] == "SUCCEEDED"
    assert outcome["result"] == {"content_type": "application/json", "body": {"resource": "fixture"}}
    assert outcome["settlement"] == {
        "network": BASE_SEPOLIA_NETWORK,
        "transaction": TXID,
        "payer": PAYER,
        "asset": BASE_SEPOLIA_USDC,
        "pay_to": PAYEE,
        "amount_atomic": "250000",
        "verified": True,
        "authorization_verified": True,
        "block_number": 16,
    }
    assert len(server.paid) == 1
    assert [
        json.loads(request.content)["method"] for request in server.calls if request.method == "POST"
    ] == [
        "eth_chainId",
        "eth_chainId",
        "eth_getTransactionReceipt",
    ]
    assert "signature" not in json.dumps(outcome).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("paid_status", [302, 402, 500])
async def test_ambiguous_paid_response_is_never_automatically_retried(monkeypatch, paid_status):
    server = FixtureServer(paid_status=paid_status)
    result = await client(server, monkeypatch).pay(action())
    assert result["status"] == "UNCERTAIN"
    assert len(server.paid) == 1
    assert result["result"] is None and result["settlement"] is None


@pytest.mark.asyncio
async def test_paid_transport_failure_is_secret_safe_and_not_retried(monkeypatch):
    server = FixtureServer()

    def handler(request):
        if request.method == "GET":
            server.paid.append(request)
            raise RuntimeError("private signing secret and payment signature must not escape")
        return server(request)

    outcome = await client(handler, monkeypatch).pay(action())
    assert outcome == {
        "status": "UNCERTAIN",
        "reason": "X402_NETWORK_UNAVAILABLE",
        "result": None,
        "settlement": None,
    }
    assert len(server.paid) == 1


@pytest.mark.asyncio
async def test_mainnet_rpc_is_rejected_before_key_loading_or_signing(monkeypatch):
    server = FixtureServer(chain=8453)
    candidate = client(server)

    async def forbidden(*args):
        pytest.fail("Wrong chain must be rejected before signing")

    monkeypatch.setattr(candidate, "_create_payload", forbidden)
    outcome = await candidate.pay(action())
    assert outcome["status"] == "UNCERTAIN" and outcome["reason"] == "X402_WRONG_CHAIN"
    assert not server.paid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"network": "eip155:8453"},
        {"scheme": "upto"},
        {"asset": PAYEE},
        {"pay_to": "0x" + "00" * 20},
        {"amount_atomic": "500001"},
        {"amount_atomic": "1.0"},
        {"amount_atomic": "01"},
        {"max_timeout_seconds": 301},
        {"max_timeout_seconds": True},
        {"max_total_minor": True},
    ],
)
async def test_invalid_terms_never_reach_rpc_or_signer(monkeypatch, change):
    server = FixtureServer()
    result = await client(server, monkeypatch).pay(action(**change))
    assert result["status"] == "UNCERTAIN"
    assert not server.calls


@pytest.mark.asyncio
async def test_permit2_and_wrong_eip712_domain_are_rejected_before_signing(monkeypatch):
    server = FixtureServer()
    for extra in ({"assetTransferMethod": "permit2"}, {"name": "Other Coin"}, {"version": "1"}):
        approved = action()
        approved["payment_requirements"]["extra"] = extra
        result = await client(server, monkeypatch).pay(approved)
        assert result["status"] == "UNCERTAIN"
    assert not server.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("server", [FixtureServer(settlement=False), FixtureServer(proof={})])
async def test_http_success_or_merchant_claim_alone_is_not_settlement(monkeypatch, server):
    result = await client(server, monkeypatch).pay(action())
    assert result["status"] == "UNCERTAIN"
    assert result["result"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payer", [None, PAYER, PAYEE])
async def test_optional_merchant_payer_cannot_replace_actual_signer_proof(monkeypatch, payer):
    server = FixtureServer()

    def handler(request):
        response = server(request)
        if request.method == "GET":
            settlement = {"success": True, "network": BASE_SEPOLIA_NETWORK, "transaction": TXID}
            if payer is not None:
                settlement["payer"] = payer
            return httpx.Response(200, headers={"PAYMENT-RESPONSE": encoded(settlement)}, json={"ok": True})
        return response

    outcome = await client(handler, monkeypatch).pay(action())
    assert outcome["status"] == ("UNCERTAIN" if payer == PAYEE else "SUCCEEDED")
    if outcome["status"] == "SUCCEEDED":
        assert outcome["settlement"]["payer"] == PAYER


@pytest.mark.asyncio
@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize("echo_header", [False, True])
async def test_merchant_cannot_echo_payment_authority_into_persisted_result(
    monkeypatch, escaped, echo_header
):
    server = FixtureServer()

    def handler(request):
        response = server(request)
        if request.method == "GET":
            authority = (
                request.headers["payment-signature"]
                if echo_header
                else server.paid[-1]["payload"]["signature"]
            )
            body = json.dumps({"echo": authority})
            if escaped:
                body = '{"echo":"\\u' + f"{ord(authority[0]):04x}" + authority[1:] + '"}'
            return httpx.Response(200, headers=response.headers, content=body)
        return response

    outcome = await client(handler, monkeypatch).pay(action())
    assert outcome["status"] == "UNCERTAIN" and outcome["reason"] == "X402_UNSAFE_RESULT"
    assert outcome["result"] is None


def test_key_file_permissions_symlinks_and_errors_are_secret_safe(tmp_path):
    key = tmp_path / "operator-secret.key"
    secret = "do-not-print-this-operator-secret"
    key.write_text(secret)
    key.chmod(0o600)
    for path in (key, tmp_path / "missing-key"):
        with pytest.raises(X402Error) as caught:
            adapter._load_signer(str(path))
        assert secret not in str(caught.value) and str(path) not in repr(caught.value)
        assert caught.value.__suppress_context__ is True
    key.chmod(0o644)
    with pytest.raises(X402Error):
        adapter._load_signer(str(key))
    key.chmod(0o600)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(key)
    with pytest.raises(X402Error):
        adapter._load_signer(str(symlink))
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(X402Error):
        adapter._load_signer(str(fifo))
    assert str(key) not in repr(X402Client(str(key)))


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [None, {}, {"name": "USDC"}, {"name": "USDC", "version": "2"}])
async def test_optional_sdk_manual_api_preserves_approved_metadata_without_wallet_generation(
    monkeypatch, extra
):
    pytest.importorskip("x402")
    pytest.importorskip("eth_account")
    signed = []

    class FakeSigner:
        address = PAYER

        def sign_typed_data(self, domain, types, primary_type, message):
            signed.append((domain, primary_type, message))
            assert domain.chain_id == 84532
            assert domain.verifying_contract.lower() == BASE_SEPOLIA_USDC.lower()
            assert domain.name == "USDC" and domain.version == "2"
            assert primary_type == "TransferWithAuthorization"
            assert message["to"].lower() == PAYEE.lower()
            return bytes.fromhex("44" * 65)

    monkeypatch.setattr(adapter, "_load_signer", lambda path: FakeSigner())
    approved = action(amount_atomic="2500000", total_minor=250, max_total_minor=500)
    if extra is None:
        approved["payment_requirements"].pop("extra")
    else:
        approved["payment_requirements"]["extra"] = extra
    result, payer = await client(FixtureServer())._create_payload(approved)
    assert payer == PAYER and len(signed) == 1
    assert result["accepted"] == approved["payment_requirements"]
    assert result["resource"] == approved["resource"]
    assert result["payload"]["authorization"]["value"] == "2500000"
    assert len(result["payload"]["authorization"]["nonce"]) == 66
    assert result["accepted"]["merchantRevision"] == "approved-exactly"
    assert result["resource"]["merchantMetadata"] == {"revision": 1}
    server = FixtureServer()
    outcome = await client(server).pay(approved)
    assert outcome["status"] == "SUCCEEDED"
    assert len(server.paid) == 1 and len(signed) == 2
    assert server.paid[0]["accepted"] == approved["payment_requirements"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_reads", [1, 2])
async def test_pending_receipt_is_polled_without_resigning_or_repeating_paid_get(monkeypatch, pending_reads):
    server = FixtureServer()
    reads = 0
    signatures = []

    def handler(request):
        nonlocal reads
        response = server(request)
        if request.method == "POST" and json.loads(request.content)["method"] == "eth_getTransactionReceipt":
            reads += 1
            if reads <= pending_reads:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
        return response

    candidate = client(handler, receipt_timeout_seconds=0.5, receipt_poll_interval_seconds=0.001)

    async def create_payload(approved):
        signatures.append(NONCE)
        return payload(approved), PAYER

    monkeypatch.setattr(candidate, "_create_payload", create_payload)
    outcome = await candidate.pay(action())
    assert outcome["status"] == "SUCCEEDED" and outcome["settlement"]["block_number"] == 16
    assert signatures == [NONCE]
    assert len(server.paid) == 1 and reads == pending_reads + 1
    rpc_calls = [json.loads(request.content) for request in server.calls if request.method == "POST"]
    assert [call["method"] for call in rpc_calls] == ["eth_chainId", "eth_chainId"] + [
        "eth_getTransactionReceipt"
    ] * reads
    assert all(call["params"] == [TXID] for call in rpc_calls[2:])


@pytest.mark.asyncio
async def test_receipt_polling_timeout_remains_uncertain_with_one_payment_attempt(monkeypatch):
    server = FixtureServer()

    def handler(request):
        response = server(request)
        if request.method == "POST" and json.loads(request.content)["method"] == "eth_getTransactionReceipt":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
        return response

    candidate = client(handler, monkeypatch, receipt_timeout_seconds=0.025, receipt_poll_interval_seconds=0.002)
    outcome = await asyncio.wait_for(candidate.pay(action()), timeout=1)
    assert outcome == {
        "status": "UNCERTAIN", "reason": "X402_SETTLEMENT_TIMEOUT", "result": None, "settlement": None,
    }
    assert len(server.paid) == 1
    receipt_calls = [
        json.loads(request.content) for request in server.calls
        if request.method == "POST" and json.loads(request.content)["method"] == "eth_getTransactionReceipt"
    ]
    assert receipt_calls and all(call["params"] == [TXID] for call in receipt_calls)


@pytest.mark.asyncio
async def test_total_receipt_deadline_cancels_a_stalled_rpc_read(monkeypatch):
    server = FixtureServer()
    read_cancelled = asyncio.Event()

    async def handler(request):
        if request.method == "POST" and json.loads(request.content)["method"] == "eth_getTransactionReceipt":
            server.calls.append(request)
            try:
                await asyncio.Future()
            finally:
                read_cancelled.set()
        return server(request)

    candidate = client(handler, monkeypatch, receipt_timeout_seconds=0.025, receipt_poll_interval_seconds=0.002)
    outcome = await asyncio.wait_for(candidate.pay(action()), timeout=1)
    assert outcome["status"] == "UNCERTAIN" and outcome["reason"] == "X402_SETTLEMENT_TIMEOUT"
    assert read_cancelled.is_set()
    assert len(server.paid) == 1
    assert [json.loads(request.content)["method"] for request in server.calls if request.method == "POST"] == [
        "eth_chainId", "eth_chainId", "eth_getTransactionReceipt",
    ]


@pytest.mark.asyncio
async def test_external_cancellation_during_receipt_polling_propagates_without_another_send(monkeypatch):
    server = FixtureServer()
    sleeping = asyncio.Event()
    original_sleep = asyncio.sleep

    def handler(request):
        response = server(request)
        if request.method == "POST" and json.loads(request.content)["method"] == "eth_getTransactionReceipt":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": None})
        return response

    async def pause(delay):
        if delay >= 1:
            sleeping.set()
        await original_sleep(delay)

    monkeypatch.setattr(adapter.asyncio, "sleep", pause)
    candidate = client(handler, monkeypatch)
    task = asyncio.create_task(candidate.pay(action()))
    await asyncio.wait_for(sleeping.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(server.paid) == 1
    assert [json.loads(request.content)["method"] for request in server.calls if request.method == "POST"] == [
        "eth_chainId", "eth_chainId", "eth_getTransactionReceipt",
    ]


@pytest.mark.asyncio
async def test_authorization_expiry_prevents_receipt_polling_beyond_approved_deadline(monkeypatch):
    server = FixtureServer()
    current_time = [time.time()]
    monkeypatch.setattr(adapter.time, "time", lambda: current_time[0])

    def handler(request):
        response = server(request)
        if request.method == "GET":
            current_time[0] += 61
        return response

    outcome = await client(handler, monkeypatch).pay(action())
    assert outcome["status"] == "UNCERTAIN" and outcome["reason"] == "X402_SETTLEMENT_TIMEOUT"
    assert len(server.paid) == 1
    assert [json.loads(request.content)["method"] for request in server.calls if request.method == "POST"] == [
        "eth_chainId", "eth_chainId",
    ]


@pytest.mark.asyncio
async def test_nonnull_invalid_receipt_is_terminal_instead_of_polled_again(monkeypatch):
    server = FixtureServer(proof=receipt(nonce="0x" + "77" * 32))
    outcome = await client(server, monkeypatch).pay(action())
    assert outcome["status"] == "UNCERTAIN" and outcome["reason"] == "X402_UNVERIFIED_SETTLEMENT"
    assert len(server.paid) == 1
    assert [json.loads(request.content)["method"] for request in server.calls if request.method == "POST"] == [
        "eth_chainId", "eth_chainId", "eth_getTransactionReceipt",
    ]


@pytest.mark.parametrize(
    "options",
    [
        {"receipt_timeout_seconds": 0},
        {"receipt_timeout_seconds": 13},
        {"receipt_timeout_seconds": float("inf")},
        {"receipt_poll_interval_seconds": 0},
        {"receipt_poll_interval_seconds": float("nan")},
        {"receipt_timeout_seconds": True},
    ],
)
def test_receipt_polling_configuration_is_finite_positive_and_bounded(options):
    with pytest.raises(ValueError, match="Receipt polling"):
        client(FixtureServer(), **options)

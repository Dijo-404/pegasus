"""Offline wallet protocol fixtures; these do not claim live payment evidence."""

import base64
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from pegasus.infrastructure.providers.zcash_client import (
    ZcashClient,
    ZcashError,
    payment_uri,
    zats_from_decimal,
)

ADDRESS = "utest1" + "q" * 100
TXID = "ab" * 32


def note(**changes):
    value = {"pool": 3, "scope": 0, "memo": "ORDER-42", "value": "0.00100000", "address": ADDRESS}
    return {**value, **changes}


def client(transactions, tip=123, synced=123, address=None, confirmations=1):
    def handler(request):
        assert request.url.host == "127.0.0.1"
        body = json.loads(request.content)
        query = body["query"]
        if "addressByAccount" in query:
            data = {"addressByAccount": address or {"ua": ADDRESS, "sapling": None, "ironwood": "receiver"}}
        elif "synchronize" in query:
            data = {"synchronize": synced}
        else:
            data = {"currentHeight": tip, "transactionsByAccount": transactions}
        return httpx.Response(200, json={"data": data})

    return ZcashClient(transport=httpx.MockTransport(handler), confirmations=confirmations)


def tx(notes=None, **changes):
    return {"txid": TXID, "height": 123, "notes": [note()] if notes is None else notes, **changes}


@pytest.mark.asyncio
async def test_confirmed_ironwood_payment_uses_notes_not_account_balance():
    receipt = await client([tx(value="-0.00010000")]).find_payment("ORDER-42", 100_000)
    assert receipt == {"txid": TXID, "height": 123, "confirmations": 1, "amount_zats": 100_000, "pool": 3}


@pytest.mark.asyncio
async def test_sum_matching_external_shielded_notes_only():
    transactions = [
        tx(
            [
                note(value="0.00060000"),
                note(value="0.00040000", pool=1),
                note(value="10", scope=1),
                note(value="10", memo="OTHER"),
            ]
        )
    ]
    receipt = await client(transactions).find_payment("ORDER-42", 100_000)
    assert receipt["amount_zats"] == 100_000
    assert receipt["pool"] == "mixed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"pool": 0},
        {"pool": 2},
        {"pool": True},
        {"scope": 1},
        {"scope": False},
        {"memo": "OTHER"},
        {"memo": None},
        {"value": "0.00099999"},
    ],
)
async def test_wrong_note_never_fulfills(change):
    assert await client([tx([note(**change)])]).find_payment("ORDER-42", 100_000) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"height": 0}, {"height": -1}, {"height": 124}, {"height": True}, {"txid": "unverified"}]
)
async def test_unmined_or_invalid_transaction_never_fulfills(change):
    assert await client([tx(**change)]).find_payment("ORDER-42", 100_000) is None


@pytest.mark.asyncio
async def test_confirmation_threshold_and_sync_height_are_enforced():
    assert (
        await client([tx()], tip=130, synced=123, confirmations=2).find_payment("ORDER-42", 100_000) is None
    )
    assert (await client([tx()], tip=130, synced=124, confirmations=2).find_payment("ORDER-42", 100_000))[
        "confirmations"
    ] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        {"ua": "u1" + "q" * 100, "ironwood": "receiver"},
        {"ua": "uregtest1" + "q" * 100, "ironwood": "receiver"},
        {"ua": ADDRESS, "orchard": "only-orchard"},
    ],
)
async def test_mainnet_regtest_or_orchard_only_account_is_refused(address):
    with pytest.raises(ZcashError):
        await client([tx()], address=address).find_payment("ORDER-42", 100_000)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/graphql",
        "http://192.168.0.1/graphql",
        "http://127.0.0.1:8000/graphql?key=secret",
        "http://user:pass@localhost/graphql",
        "file:///graphql",
        "http://localhost/elsewhere",
    ],
)
def test_wallet_endpoint_is_loopback_only(url):
    with pytest.raises(ZcashError):
        ZcashClient(url)


def test_zip321_memo_utf8_base64url_and_exact_amount():
    uri = payment_uri(ADDRESS, 100_001, "order नमस्ते")
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query)
    assert query["amount"] == ["0.00100001"]
    memo = query["memo"][0]
    assert "=" not in memo
    assert base64.urlsafe_b64decode(memo + "=" * (-len(memo) % 4)).decode() == "order नमस्ते"


@pytest.mark.parametrize("amount,memo", [(0, "x"), (-1, "x"), (True, "x"), (1, ""), (1, "आ" * 171)])
def test_payment_parameters_fail_closed(amount, memo):
    with pytest.raises(ZcashError):
        payment_uri(ADDRESS, amount, memo)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-0.01", "0.000000001", 0.1, None])
def test_decimal_conversion_rejects_invalid_or_lossy_values(amount):
    with pytest.raises(ZcashError):
        zats_from_decimal(amount)


@pytest.mark.asyncio
async def test_wallet_rpc_error_does_not_leak_upstream_secret():
    def handler(request):
        return httpx.Response(200, json={"errors": [{"message": "secret-seed-do-not-copy"}]})

    wallet = ZcashClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ZcashError) as error:
        await wallet.check()
    assert "secret-seed" not in str(error.value)

"""Private checkout uses only the receiving-wallet and repository ports."""

import time

import pytest

from pegasus.application.private_checkout_service import PrivateCheckoutService
from pegasus.domain.exceptions import Denied
from pegasus.domain.private_checkout_policy import PrivateCheckoutPolicy, validate_redemption


class MemoryOrders:
    def __init__(self):
        self.orders = {}

    def insert_private(self, order):
        self.orders[order["id"]] = order

    def private(self, order_id):
        return self.orders[order_id]

    def confirm_private(self, order_id, payment):
        order = self.orders[order_id]
        order.update(status="CONFIRMED", payment=payment, entitlement_expires_at=int(time.time()) + 300)
        return order

    def redeem(self, order_id):
        order = self.orders[order_id]
        validate_redemption(order, int(time.time()))
        order["status"] = "REDEEMED"


class ReceivingWallet:
    def __init__(self):
        self.address_calls = 0
        self.payment_calls = []
        self.payment = None

    async def address(self):
        self.address_calls += 1
        return "fixture-testnet-address"

    def payment_uri(self, address, amount_zats, memo):
        return f"fixture-payment:{address}:{amount_zats}:{memo}"

    async def find_payment(self, memo, amount_zats):
        self.payment_calls.append((memo, amount_zats))
        return self.payment


def service(enabled=True):
    repository, wallet = MemoryOrders(), ReceivingWallet()
    checkout = PrivateCheckoutService(
        PrivateCheckoutPolicy(enabled=enabled, amount_zats=100000), repository, wallet
    )
    return checkout, repository, wallet


async def test_resource_stays_locked_until_watcher_confirms_then_redeems_once():
    checkout, repository, wallet = service()
    order = await checkout.create_order()
    assert order["status"] == "AWAITING_PAYMENT"
    assert order["memo"].startswith("PEGASUS-")
    assert order["amount_zats"] == 100000
    assert order["memo"] in order["payment_uri"]
    with pytest.raises(Denied) as error:
        checkout.redeem_order(order["id"])
    assert error.value.code == "NOT_REDEEMABLE"

    assert (await checkout.refresh_order(order["id"]))["status"] == "AWAITING_PAYMENT"
    wallet.payment = {"txid": "fixture-confirmed-payment", "confirmations": 1, "amount_zats": 100000}
    assert (await checkout.refresh_order(order["id"]))["status"] == "CONFIRMED"
    assert wallet.payment_calls == [(order["memo"], 100000)] * 2
    assert (await checkout.refresh_order(order["id"]))["status"] == "CONFIRMED"
    assert len(wallet.payment_calls) == 2  # Terminal order does not reprocess the same payment.

    assert "content" in checkout.redeem_order(order["id"])
    assert repository.private(order["id"])["status"] == "REDEEMED"
    with pytest.raises(Denied):
        checkout.redeem_order(order["id"])


async def test_disabled_private_checkout_does_not_contact_wallet():
    checkout, repository, wallet = service(enabled=False)
    with pytest.raises(Denied) as error:
        await checkout.create_order()
    assert error.value.code == "ZCASH_NOT_CONFIGURED"
    assert wallet.address_calls == 0
    assert repository.orders == {}

"""Independent private-resource purchase and redemption use cases."""

import time
import uuid

from pegasus.domain.exceptions import Denied
from pegasus.domain.private_checkout_policy import PrivateCheckoutPolicy

from .ports import PaymentVerifier, PrivateOrderRepository


class PrivateCheckoutService:
    def __init__(
        self, policy: PrivateCheckoutPolicy, repository: PrivateOrderRepository, verifier: PaymentVerifier
    ):
        self.policy, self.repository, self.verifier = policy, repository, verifier

    def _require_enabled(self) -> None:
        if not self.policy.enabled:
            raise Denied("ZCASH_NOT_CONFIGURED", "Enable the local testnet receiver in .env first.")

    async def create_order(self) -> dict:
        self._require_enabled()
        address = await self.verifier.address()
        memo = "PEGASUS-" + uuid.uuid4().hex
        order = {
            "id": "zo_" + uuid.uuid4().hex,
            "memo": memo,
            "address": address,
            "amount_zats": self.policy.amount_zats,
            "payment_uri": self.verifier.payment_uri(address, self.policy.amount_zats, memo),
            "status": "AWAITING_PAYMENT",
            "created_at": int(time.time()),
            "payment": None,
        }
        self.repository.insert_private(order)
        return order

    async def refresh_order(self, order_id: str) -> dict:
        self._require_enabled()
        order = self.repository.private(order_id)
        if order["status"] == "AWAITING_PAYMENT":
            payment = await self.verifier.find_payment(order["memo"], order["amount_zats"])
            if payment:
                return self.repository.confirm_private(order_id, payment)
        return order

    def redeem_order(self, order_id: str) -> dict:
        self._require_enabled()
        self.repository.redeem(order_id)
        return {
            "content": "Welcome to the Pegasus private resource. Your shielded testnet payment was independently verified and this single-use entitlement is now consumed."
        }

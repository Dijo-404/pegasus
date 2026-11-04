"""Separate shielded-testnet resource endpoints."""

from fastapi import APIRouter, Depends

from pegasus.application.private_checkout_service import PrivateCheckoutService
from ..authentication import HttpAuthentication
from ..schemas import EmptyRequest


def build_private_checkout_router(
    service: PrivateCheckoutService, authentication: HttpAuthentication
) -> APIRouter:
    router = APIRouter(prefix="/api/private", dependencies=[Depends(authentication.actor)])

    @router.post("/orders")
    async def create_order(body: EmptyRequest):
        return await service.create_order()

    @router.post("/orders/{order_id}/refresh")
    async def refresh_order(order_id: str):
        return await service.refresh_order(order_id)

    @router.post("/orders/{order_id}/redeem")
    async def redeem_order(order_id: str):
        return service.redeem_order(order_id)

    return router

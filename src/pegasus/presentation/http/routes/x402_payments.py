"""Explicit proposal, owner approval and one attempt for external x402 APIs."""

from fastapi import APIRouter, Depends

from pegasus.application.x402_service import X402Service
from ..authentication import HttpAuthentication
from ..projections import present_x402_intent
from ..schemas import ApiPaymentProposalRequest, PurchaseApprovalRequest, PurchaseExecutionRequest


def build_x402_router(service: X402Service, authentication: HttpAuthentication) -> APIRouter:
    router = APIRouter(prefix="/api/x402/intents")

    @router.post("")
    async def propose(body: ApiPaymentProposalRequest, role=Depends(authentication.actor)):
        return present_x402_intent(await service.propose(body.model_dump()))

    @router.get("")
    async def intents(role=Depends(authentication.actor)):
        return {"intents": [present_x402_intent(value) for value in service.list_intents()]}

    @router.get("/{intent_id}")
    async def get_intent(intent_id: str, role=Depends(authentication.actor)):
        return present_x402_intent(service.get_intent(intent_id))

    @router.post("/{intent_id}/approve", dependencies=[Depends(authentication.owner)])
    async def approve(intent_id: str, body: PurchaseApprovalRequest):
        value = service.approve(intent_id, body.digest)
        return {**value, "intent": present_x402_intent(value["intent"])}

    @router.post("/{intent_id}/execute")
    async def execute(intent_id: str, body: PurchaseExecutionRequest, role=Depends(authentication.actor)):
        return present_x402_intent(await service.execute(intent_id, body.grant))

    @router.get("/{intent_id}/audit", dependencies=[Depends(authentication.actor)])
    async def audit(intent_id: str):
        return {"events": service.get_audit(intent_id)}

    return router

"""Commerce endpoints; financial decisions are delegated to application use cases."""

from fastapi import APIRouter, Depends, Query

from pegasus.application.commerce_service import CommerceService
from ..authentication import HttpAuthentication
from ..projections import present_intent
from ..schemas import PurchaseApprovalRequest, PurchaseExecutionRequest, PurchaseProposalRequest


def build_commerce_router(service: CommerceService, authentication: HttpAuthentication) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/catalog/search", dependencies=[Depends(authentication.actor)])
    async def search(
        q: str = Query(min_length=1, max_length=200),
        country: str = "IN",
        intent: str = "User-requested shopping",
    ):
        return {"products": await service.search_catalog(q, country, intent)}

    @router.get("/catalog/products/{product_id}", dependencies=[Depends(authentication.actor)])
    async def details(product_id: str):
        return await service.product_details(product_id)

    @router.post("/intents")
    async def propose(body: PurchaseProposalRequest, role=Depends(authentication.actor)):
        return present_intent(await service.propose(body.model_dump()), owner=role == "owner")

    @router.get("/intents")
    async def intents(role=Depends(authentication.actor)):
        return {"intents": [present_intent(value, owner=role == "owner") for value in service.list_intents()]}

    @router.get("/intents/{intent_id}")
    async def get_intent(intent_id: str, role=Depends(authentication.actor)):
        return present_intent(service.get_intent(intent_id), owner=role == "owner")

    @router.post("/intents/{intent_id}/approve", dependencies=[Depends(authentication.owner)])
    async def approve(intent_id: str, body: PurchaseApprovalRequest):
        result = service.approve(intent_id, body.digest)
        return {**result, "intent": present_intent(result["intent"], owner=True)}

    @router.post("/intents/{intent_id}/execute")
    async def execute(intent_id: str, body: PurchaseExecutionRequest, role=Depends(authentication.actor)):
        return present_intent(await service.execute(intent_id, body.grant), owner=role == "owner")

    @router.post("/intents/{intent_id}/refresh")
    async def refresh(intent_id: str, role=Depends(authentication.actor)):
        return present_intent(await service.refresh(intent_id), owner=role == "owner")

    @router.get("/intents/{intent_id}/audit", dependencies=[Depends(authentication.actor)])
    async def audit(intent_id: str):
        return {"events": service.get_audit(intent_id)}

    return router

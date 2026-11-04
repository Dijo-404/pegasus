"""Public health, non-sensitive configuration, session role, and dashboard endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..authentication import HttpAuthentication
from ..settings import HttpSettings


def build_system_router(settings: HttpSettings, authentication: HttpAuthentication) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    @router.get("/api/config")
    async def config():
        return {
            "mode": "live",
            "bitrefill_configured": settings.bitrefill_configured,
            "zcash_configured": settings.zcash_configured,
            "caps": {
                "per_purchase_minor": settings.max_purchase_minor,
                "per_day_minor": settings.max_daily_minor,
                "currency": "USD",
                "day_timezone": "Asia/Kolkata",
            },
            "allowed_products": sorted(settings.allowed_products),
            "allowed_countries": sorted(settings.allowed_countries),
            "merchant": {"name": "Pegasus private demo resource", "amount_zats": settings.zcash_amount_zats},
        }

    @router.get("/api/session")
    async def session(role=Depends(authentication.actor)):
        return {"role": role}

    @router.get("/")
    async def index():
        return FileResponse(settings.static_directory / "index.html")

    return router

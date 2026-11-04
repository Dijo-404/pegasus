"""Build the HTTP interface from application services supplied by bootstrap."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pegasus.application.commerce_service import CommerceService
from pegasus.application.private_checkout_service import PrivateCheckoutService
from .authentication import HttpAuthentication
from .error_handlers import register_error_handlers
from .middleware import register_middleware
from .routes.commerce import build_commerce_router
from .routes.private_checkout import build_private_checkout_router
from .routes.system import build_system_router
from .settings import HttpSettings


def build_http_app(
    commerce: CommerceService, private_checkout: PrivateCheckoutService, settings: HttpSettings
) -> FastAPI:
    app = FastAPI(title="Pegasus", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.commerce = commerce
    app.state.private_checkout = private_checkout
    authentication = HttpAuthentication(settings)
    register_middleware(app)
    register_error_handlers(app)
    app.include_router(build_system_router(settings))
    app.include_router(build_commerce_router(commerce, authentication))
    app.include_router(build_private_checkout_router(private_checkout, authentication))
    app.mount("/static", StaticFiles(directory=settings.static_directory, check_dir=False), name="static")
    return app

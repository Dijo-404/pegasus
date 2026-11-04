"""Translate safe domain failures into HTTP responses without echoing sensitive input."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pegasus.domain.exceptions import Denied, IntegrationError

HTTP_STATUS_BY_CODE = {
    "UNAUTHORIZED": 401,
    "OWNER_REQUIRED": 403,
    "NOT_FOUND": 404,
    "ZCASH_NOT_CONFIGURED": 503,
    "X402_NOT_CONFIGURED": 503,
    "X402_DISABLED": 503,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Denied)
    async def denied_handler(request, error):
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message}},
            HTTP_STATUS_BY_CODE.get(error.code, 409),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        # Pydantic's default response echoes inputs, including possible credentials or PII.
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "Request fields have invalid values or unexpected fields.",
                }
            },
            422,
        )

    @app.exception_handler(IntegrationError)
    async def integration_handler(request, error):
        return JSONResponse({"error": {"code": error.code, "message": str(error)}}, 502)

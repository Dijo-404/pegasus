"""Explicit host and browser boundaries, bounded bodies, and security headers."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

MAX_BODY_BYTES = 16384


def register_middleware(app: FastAPI, allowed_hosts: frozenset[str]) -> None:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(allowed_hosts), www_redirect=False)

    @app.middleware("http")
    async def browser_boundary(request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"error": {"code": "ORIGIN_DENIED", "message": "Same-origin requests required."}}, 403
            )
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse(
                {"error": {"code": "INVALID_INPUT", "message": "Invalid content length."}}, 400
            )
        if length > MAX_BODY_BYTES:
            return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": "Request too large."}}, 413)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": {"code": "BODY_TOO_LARGE", "message": "Request too large."}}, 413
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

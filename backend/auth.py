from fastapi import Header, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.config import settings

EXEMPT_PATHS = {"/health", "/", "/docs", "/openapi.json", "/api/knowledge/ask"}
EXEMPT_PREFIXES = ("/api/stream/",)
EXEMPT_METHODS = {"GET", "OPTIONS", "HEAD"}


def verify_api_key(x_api_key: str = Header(...)) -> str:
    if x_api_key != settings.OPS_AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


class AuthMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key on all non-GET, non-exempt requests."""

    async def dispatch(self, request: Request, call_next):
        if request.method in EXEMPT_METHODS:
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)

        api_key = request.headers.get("x-api-key")
        if api_key != settings.OPS_AGENT_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)

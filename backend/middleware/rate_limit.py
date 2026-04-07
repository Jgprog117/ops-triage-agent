"""Per-IP, per-path token-bucket rate limiting for selected endpoints.

The middleware applies only to paths registered in
:data:`RATE_LIMITED_PATHS`. All other requests pass through untouched.
Buckets are kept in process memory keyed by ``(path, client_ip)`` and
refill in one bulk step at the end of each :data:`WINDOW_SECONDS` window.
"""

import time
from collections import defaultdict
from typing import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

# Paths to rate-limit and their max requests per window
RATE_LIMITED_PATHS: dict[str, int] = {
    "/api/knowledge/ask": 10,
}

WINDOW_SECONDS = 60


class _TokenBucket:
    """Mutable token-bucket state for one ``(path, client_ip)`` pair.

    Attributes:
        tokens: Remaining tokens in the current window.
        last_refill: Monotonic timestamp of the last bulk refill.
    """

    __slots__ = ("tokens", "last_refill")

    def __init__(self, max_tokens: int) -> None:
        """Inits the bucket full and timestamps it as just refilled.

        Args:
            max_tokens: Initial token count.
        """
        self.tokens = max_tokens
        self.last_refill = time.monotonic()


_buckets: dict[str, dict[str, _TokenBucket]] = defaultdict(dict)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces :data:`RATE_LIMITED_PATHS`."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Consumes a token (or 429s) for rate-limited paths.

        Args:
            request: The incoming request.
            call_next: The downstream ASGI handler.

        Returns:
            The downstream response when the request is allowed, or a
            429 ``JSONResponse`` when the bucket is empty.
        """
        path = request.url.path
        max_requests = RATE_LIMITED_PATHS.get(path)

        if max_requests is None:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        bucket = _buckets[path].get(client_ip)
        if bucket is None:
            bucket = _TokenBucket(max_requests)
            _buckets[path][client_ip] = bucket

        # Refill tokens based on elapsed time
        elapsed = now - bucket.last_refill
        if elapsed >= WINDOW_SECONDS:
            bucket.tokens = max_requests
            bucket.last_refill = now

        if bucket.tokens <= 0:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )

        bucket.tokens -= 1
        return await call_next(request)

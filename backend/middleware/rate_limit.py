import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Paths to rate-limit and their max requests per window
RATE_LIMITED_PATHS: dict[str, int] = {
    "/api/knowledge/ask": 10,
}

WINDOW_SECONDS = 60


class _TokenBucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, max_tokens: int):
        self.tokens = max_tokens
        self.last_refill = time.monotonic()


_buckets: dict[str, dict[str, _TokenBucket]] = defaultdict(dict)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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

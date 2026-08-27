"""
Rate limiting middleware — in-memory fallback (Redis disabled).
Uses a simple per-process dict. Resets on server restart.
Pure ASGI middleware to avoid BaseHTTPMiddleware event-loop conflicts with Motor/Beanie.
"""
import time
from collections import defaultdict
from loguru import logger

# Simple in-memory store: key → (count, window_start)
_rate_store: dict = defaultdict(lambda: [0, 0.0])


class RateLimitMiddleware:
    """Pure ASGI rate limiting middleware — in-memory, no Redis required."""

    def __init__(self, app, calls_per_minute: int = 120):
        self.app = app
        self.calls_per_minute = calls_per_minute

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Skip rate limiting for health/docs
        if path in ["/api/health", "/api/docs", "/api/redoc", "/api/openapi.json"]:
            await self.app(scope, receive, send)
            return

        # Extract client IP from scope
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        key = f"{client_ip}"

        now = time.time()
        entry = _rate_store[key]
        if now - entry[1] > 60:
            # New window
            entry[0] = 1
            entry[1] = now
        else:
            entry[0] += 1

        if entry[0] > self.calls_per_minute:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            # Send 429 response
            body = b'{"detail": "Rate limit exceeded. Please try again later."}'
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": headers,
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        await self.app(scope, receive, send)
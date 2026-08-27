"""
Logging middleware - Log all requests and responses.
Pure ASGI middleware to avoid BaseHTTPMiddleware event-loop conflicts with Motor/Beanie.
"""
from loguru import logger
import time
import uuid


class LoggingMiddleware:
    """Pure ASGI middleware to log all incoming requests and responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Generate request ID
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        # Extract request info
        method = scope.get("method", "")
        path = scope.get("path", "")

        # Log request
        logger.info(f"Request {request_id}: {method} {path}")

        start_time = time.time()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            process_time = time.time() - start_time
            # Log response
            logger.info(
                f"Response {request_id}: {status_code} - "
                f"Processed in {process_time:.3f}s"
            )
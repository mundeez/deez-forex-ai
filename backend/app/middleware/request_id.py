"""
Request ID middleware for tracing requests across the application.
"""

import uuid
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.middleware.request_id")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to each incoming request for tracing."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

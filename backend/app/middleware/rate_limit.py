"""
Simple in-memory rate limiter for FastAPI.
Uses a sliding window algorithm. In production, replace with Redis-backed limiter.
"""

import time
import logging
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.middleware.rate_limit")

# Window size in seconds
WINDOW_SIZE = 60

# Limits per endpoint pattern: (requests_per_window, endpoint_pattern)
DEFAULT_LIMIT = 100  # 100 requests per minute default
LIMITS: list[Tuple[int, str]] = [
    (10, "/api/v1/settings"),      # Settings changes: 10/min
    (5, "/api/v1/trades"),         # Trade execution: 5/min
    (5, "/api/v1/positions"),      # Position close: 5/min
    (5, "/api/v1/ai/analyze"),     # AI analysis trigger: 5/min
    (30, "/api/v1/market"),        # Market data: 30/min
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using sliding window (in-memory)."""

    def __init__(self, app, window_size: int = WINDOW_SIZE):
        super().__init__(app)
        self.window_size = window_size
        # client_ip -> {endpoint -> [timestamps]}
        self._requests: Dict[str, Dict[str, list]] = {}

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health, docs, and WebSocket
        path = request.url.path
        if path in ("/health", "/docs", "/openapi.json", "/ws"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Determine limit for this endpoint
        limit = DEFAULT_LIMIT
        for l, pattern in LIMITS:
            if pattern in path:
                limit = l
                break

        # Clean old entries periodically
        if hash(path) % 100 == 0:
            self._cleanup(now)

        # Check rate limit
        client_requests = self._requests.setdefault(client_ip, {})
        endpoint_requests = client_requests.setdefault(path, [])

        # Remove entries outside the window
        cutoff = now - self.window_size
        endpoint_requests[:] = [t for t in endpoint_requests if t > cutoff]

        if len(endpoint_requests) >= limit:
            logger.warning("Rate limit exceeded for %s on %s (%d/%d)", client_ip, path, len(endpoint_requests), limit)
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")

        endpoint_requests.append(now)
        return await call_next(request)

    def _cleanup(self, now: float):
        """Remove stale entries to prevent memory growth."""
        cutoff = now - self.window_size * 2
        for client_ip in list(self._requests.keys()):
            for endpoint in list(self._requests[client_ip].keys()):
                self._requests[client_ip][endpoint] = [
                    t for t in self._requests[client_ip][endpoint] if t > cutoff
                ]
                if not self._requests[client_ip][endpoint]:
                    del self._requests[client_ip][endpoint]
            if not self._requests[client_ip]:
                del self._requests[client_ip]

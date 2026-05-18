"""Tests for custom middleware."""

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware


class TestRateLimitMiddleware:
    def test_rate_limit_allows_under_limit(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, window_size=60)

        @app.get("/api/v1/test")
        def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        for _ in range(5):
            response = client.get("/api/v1/test")
            assert response.status_code == 200

    def test_rate_limit_blocks_over_limit(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, window_size=60)

        @app.get("/api/v1/settings")
        def settings_endpoint():
            return {"ok": True}

        client = TestClient(app)
        # Endpoint limit is 10/min for /api/v1/settings
        for _ in range(10):
            response = client.get("/api/v1/settings")
            assert response.status_code == 200

        # 11th request should be rate limited
        response = client.get("/api/v1/settings")
        assert response.status_code == 429

    def test_skips_health_and_docs(self):
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, window_size=60)

        @app.get("/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)
        for _ in range(200):
            response = client.get("/health")
            assert response.status_code == 200


class TestRequestIdMiddleware:
    def test_adds_request_id_header(self):
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) == 8  # short UUID prefix

    def test_preserves_existing_request_id(self):
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        existing_id = "abc123"
        response = client.get("/test", headers={"x-request-id": existing_id})
        assert response.headers["x-request-id"] == existing_id

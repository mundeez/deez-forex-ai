"""Tests for the Myfxbook JSON API client (v1.12.7/v1.12.8).

Covers scrape_myfxbook() — credential gating, login/session handling,
percentage normalization, symbol filtering, and DB persistence.
"""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import select

from app.services.data.retail_client import scrape_myfxbook, SYMBOLS
from app.tests.conftest import AsyncSessionLocal
from app import models


class _FakeResp:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status

    def json(self):
        return self._payload


class _FakeMyfxbookClient:
    """Stand-in for httpx.AsyncClient routed by URL suffix."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.calls.append(url)
        for suffix, resp in self.routes.items():
            if url.endswith(suffix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return _FakeResp({"error": True, "message": "not mocked"}, status=404)


def _routes(**kw):
    return {
        "login.json": kw.get("login", _FakeResp({"error": False, "session": "sess123"})),
        "get-community-outlook.json": kw.get("outlook", _FakeResp({"error": False, "symbols": []})),
        "logout.json": _FakeResp({"error": False}),
    }


@pytest.mark.asyncio
async def test_scrape_myfxbook_no_credentials(db_engine):
    """No MYFXBOOK_EMAIL/PASSWORD → returns 0 without touching HTTP."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("MYFXBOOK_EMAIL", "MYFXBOOK_PASSWORD")}
    with patch.dict(os.environ, env, clear=True):
        async with AsyncSessionLocal() as db:
            n = await scrape_myfxbook(db)
    assert n == 0


@pytest.mark.asyncio
async def test_scrape_myfxbook_login_error(db_engine):
    """Myfxbook rejects credentials → returns 0, no rows written."""
    routes = _routes(login=_FakeResp({"error": True, "message": "Wrong email/password."}))
    with patch.dict(os.environ, {"MYFXBOOK_EMAIL": "a@b.c", "MYFXBOOK_PASSWORD": "pw"}):
        with patch("app.services.data.retail_client.httpx.AsyncClient",
                   return_value=_FakeMyfxbookClient(routes)):
            async with AsyncSessionLocal() as db:
                n = await scrape_myfxbook(db)
    assert n == 0


@pytest.mark.asyncio
async def test_scrape_myfxbook_success(db_engine):
    """Full happy path: login → outlook → normalized rows persisted + logout."""
    outlook = _FakeResp({"error": False, "symbols": [
        {"name": "EURUSD", "longPercentage": 0.87, "shortPercentage": 0.13},
        {"name": "USDCAD", "longPercentage": 0.08, "shortPercentage": 0.92},
        {"name": "XAUUSD", "longPercentage": 0.69, "shortPercentage": 0.31},
        {"name": "SPX500", "longPercentage": 0.50, "shortPercentage": 0.50},  # untracked
    ]})
    fake = _FakeMyfxbookClient(_routes(outlook=outlook))

    with patch.dict(os.environ, {"MYFXBOOK_EMAIL": "a@b.c", "MYFXBOOK_PASSWORD": "pw"}):
        with patch("app.services.data.retail_client.httpx.AsyncClient", return_value=fake):
            async with AsyncSessionLocal() as db:
                n = await scrape_myfxbook(db)

    assert n == 3  # SPX500 filtered out

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(models.RetailSentiment).where(models.RetailSentiment.source == "myfxbook")
        )).scalars().all()

    by_sym = {r.symbol: r for r in rows}
    assert set(by_sym) == {"EURUSD", "USDCAD", "XAUUSD"}

    # Fractions normalized to 0-100
    assert by_sym["EURUSD"].long_pct == pytest.approx(87.0)
    assert by_sym["EURUSD"].short_pct == pytest.approx(13.0)
    assert by_sym["EURUSD"].net_score == pytest.approx(0.74)
    # Deep-short symbol flips sign
    assert by_sym["USDCAD"].net_score == pytest.approx(-0.84)
    # All rows share one snapshot timestamp
    assert len({r.timestamp for r in rows}) == 1
    # Session was logged out
    assert any("logout.json" in u for u in fake.calls)


@pytest.mark.asyncio
async def test_scrape_myfxbook_pct_range_not_rescaled(db_engine):
    """Values already in 0-100 range must not be multiplied again."""
    outlook = _FakeResp({"error": False, "symbols": [
        {"name": "USDJPY", "longPercentage": 65.0, "shortPercentage": 35.0},
    ]})
    with patch.dict(os.environ, {"MYFXBOOK_EMAIL": "a@b.c", "MYFXBOOK_PASSWORD": "pw"}):
        with patch("app.services.data.retail_client.httpx.AsyncClient",
                   return_value=_FakeMyfxbookClient(_routes(outlook=outlook))):
            async with AsyncSessionLocal() as db:
                n = await scrape_myfxbook(db)
                row = (await db.execute(
                    select(models.RetailSentiment)
                    .where(models.RetailSentiment.symbol == "USDJPY"))).scalar_one()
    assert n == 1
    assert row.long_pct == pytest.approx(65.0)


@pytest.mark.asyncio
async def test_scrape_myfxbook_outlook_error(db_engine):
    """Outlook API returns error → 0 rows, session still logged out."""
    fake = _FakeMyfxbookClient(_routes(
        outlook=_FakeResp({"error": True, "message": "session expired"})))
    with patch.dict(os.environ, {"MYFXBOOK_EMAIL": "a@b.c", "MYFXBOOK_PASSWORD": "pw"}):
        with patch("app.services.data.retail_client.httpx.AsyncClient", return_value=fake):
            async with AsyncSessionLocal() as db:
                n = await scrape_myfxbook(db)
    assert n == 0
    assert any("logout.json" in u for u in fake.calls)


@pytest.mark.asyncio
async def test_scrape_myfxbook_login_http_failure(db_engine):
    """Network-level failure on login → 0, no exception leaks."""
    routes = _routes(login=_FakeResp({"error": False, "session": "s"}))
    routes["login.json"] = ConnectionError("boom")
    with patch.dict(os.environ, {"MYFXBOOK_EMAIL": "a@b.c", "MYFXBOOK_PASSWORD": "pw"}):
        with patch("app.services.data.retail_client.httpx.AsyncClient",
                   return_value=_FakeMyfxbookClient(routes)):
            async with AsyncSessionLocal() as db:
                n = await scrape_myfxbook(db)
    assert n == 0

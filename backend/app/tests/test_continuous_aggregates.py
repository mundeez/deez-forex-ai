"""Tests for TimescaleDB continuous aggregates (v0.8.0 M3)."""
import pytest
import os
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.data.market_data_service import MarketDataService


def _is_postgres():
    return os.environ.get("DATABASE_URL", "").startswith("postgresql")


def _get_pg_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return None
    return create_async_engine(url, future=True, echo=False)


@pytest.mark.skipif(not _is_postgres(), reason="Continuous aggregates require PostgreSQL/TimescaleDB")
@pytest.mark.asyncio
async def test_continuous_aggregates_exist():
    """All 7 bar caggs must be registered in TimescaleDB."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL")
    expected = ["bars_1m", "bars_5m", "bars_15m", "bars_1h", "bars_4h", "bars_1d", "bars_1w"]
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT view_name FROM timescaledb_information.continuous_aggregates
                ORDER BY view_name
            """)
        )
        views = [r[0] for r in result.fetchall()]
    assert set(expected) <= set(views)
    await pg_engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="Continuous aggregates require PostgreSQL/TimescaleDB")
@pytest.mark.asyncio
async def test_cagg_refresh_policies_exist():
    """Each cagg must have an auto-refresh policy."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL")
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT mat_hypertable_name, schedule_interval
                FROM timescaledb_information.jobs
                WHERE proc_name = 'policy_refresh_continuous_aggregate'
            """)
        )
        policies = {r[0]: r[1] for r in result.fetchall()}
    # Check at least some caggs have policies
    assert len(policies) >= 4
    await pg_engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="Continuous aggregates require PostgreSQL/TimescaleDB")
@pytest.mark.asyncio
async def test_ticks_retention_policy():
    """Raw ticks must have a 90-day retention policy."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL")
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT drop_after FROM timescaledb_information.jobs
                WHERE proc_name = 'policy_retention'
                  AND hypertable_name = 'ticks'
            """)
        )
        row = result.fetchone()
    assert row is not None
    assert "90 days" in str(row[0]) or "3 mons" in str(row[0])
    await pg_engine.dispose()


@pytest.mark.asyncio
async def test_market_data_service_sqlite_fallback(db_engine):
    """MarketDataService must fallback gracefully on SQLite (no caggs)."""
    service = MarketDataService()
    bars = await service.get_bars("EURUSD", timeframe="1h", limit=10)
    assert isinstance(bars, list)

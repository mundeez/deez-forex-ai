"""Tests for TimescaleDB migration and tick pipeline schema (v0.8.0 M0)."""
import pytest
import os
from datetime import datetime, timezone

from sqlalchemy import text, select, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base
from app.models import Tick, IngestionState


def _is_postgres():
    return os.environ.get("DATABASE_URL", "").startswith("postgresql")


def _get_columns(sync_conn, table_name):
    return inspect(sync_conn).get_columns(table_name)


def _get_pg_engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return None
    return create_async_engine(url, future=True, echo=False)


@pytest.mark.asyncio
async def test_ticks_table_created(db_engine):
    """The ticks table must exist with all expected columns."""
    engine = _get_pg_engine() or db_engine
    async with engine.begin() as conn:
        if _is_postgres():
            result = await conn.execute(
                text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'ticks' ORDER BY ordinal_position")
            )
            rows = result.fetchall()
            assert len(rows) == 9
            columns = [r[0] for r in rows]
        else:
            columns_info = await conn.run_sync(_get_columns, 'ticks')
            assert len(columns_info) == 9
            columns = [c['name'] for c in columns_info]

    assert "symbol" in columns
    assert "timestamp" in columns
    assert "bid" in columns
    assert "ask" in columns
    assert "spread_pips" in columns
    assert "source" in columns
    if _is_postgres():
        await engine.dispose()


@pytest.mark.asyncio
async def test_bars_table_created(db_engine):
    """The bars hypertable must exist with all expected columns."""
    engine = _get_pg_engine() or db_engine
    async with engine.begin() as conn:
        if _is_postgres():
            result = await conn.execute(
                text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'bars' ORDER BY ordinal_position")
            )
            rows = result.fetchall()
            assert len(rows) == 11
            columns = [r[0] for r in rows]
        else:
            columns_info = await conn.run_sync(_get_columns, 'bars')
            assert len(columns_info) == 11
            columns = [c['name'] for c in columns_info]

    assert "symbol" in columns
    assert "timeframe" in columns
    assert "avg_spread" in columns
    if _is_postgres():
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingestion_state_table_created(db_engine):
    """The ingestion_state checkpoint table must exist."""
    engine = _get_pg_engine() or db_engine
    async with engine.begin() as conn:
        if _is_postgres():
            result = await conn.execute(
                text("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'ingestion_state' ORDER BY ordinal_position")
            )
            rows = result.fetchall()
            assert len(rows) >= 8
            columns = [r[0] for r in rows]
        else:
            columns_info = await conn.run_sync(_get_columns, 'ingestion_state')
            assert len(columns_info) >= 8
            columns = [c['name'] for c in columns_info]

    assert "symbol" in columns
    assert "source" in columns
    assert "status" in columns
    assert "last_ingested_at" in columns
    if _is_postgres():
        await engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="TimescaleDB-specific tests require PostgreSQL")
@pytest.mark.asyncio
async def test_timescale_extension_loaded():
    """TimescaleDB extension must be installed on PostgreSQL."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL connection available")
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb'")
        )
        row = result.fetchone()
    assert row is not None
    assert row[0] == "timescaledb"
    await pg_engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="TimescaleDB-specific tests require PostgreSQL")
@pytest.mark.asyncio
async def test_ticks_is_hypertable():
    """ticks must be registered as a TimescaleDB hypertable."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL connection available")
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'ticks'")
        )
        row = result.fetchone()
    assert row is not None
    await pg_engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="TimescaleDB-specific tests require PostgreSQL")
@pytest.mark.asyncio
async def test_bars_is_hypertable():
    """bars must be registered as a TimescaleDB hypertable."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL connection available")
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'bars'")
        )
        row = result.fetchone()
    assert row is not None
    await pg_engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="TimescaleDB-specific tests require PostgreSQL")
@pytest.mark.asyncio
async def test_compression_policy_exists():
    """A compression policy must exist for the ticks hypertable."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL connection available")
    async with pg_engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT * FROM timescaledb_information.jobs
                WHERE proc_name = 'policy_compression'
                  AND hypertable_name = 'ticks'
            """)
        )
        row = result.fetchone()
    assert row is not None
    await pg_engine.dispose()


@pytest.mark.skipif(not _is_postgres(), reason="TimescaleDB-specific tests require PostgreSQL")
@pytest.mark.asyncio
async def test_existing_tables_preserved():
    """Migration must not drop existing application tables (market_data, trades, etc.)."""
    pg_engine = _get_pg_engine()
    if pg_engine is None:
        pytest.skip("No PostgreSQL connection available")
    required_tables = ["market_data", "trades", "ai_decisions", "account_snapshots", "settings"]
    async with pg_engine.begin() as conn:
        for tbl in required_tables:
            result = await conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
                {"t": tbl}
            )
            assert result.fetchone() is not None, f"Table {tbl} was dropped during migration"
    await pg_engine.dispose()


@pytest.mark.asyncio
async def test_orm_models_sync(db_session):
    """SQLAlchemy ORM models must map correctly to the DB tables."""
    state = IngestionState(
        symbol="EURUSD",
        source="dukascopy",
        status="idle",
        total_ticks=0,
    )
    db_session.add(state)
    await db_session.commit()

    result = await db_session.execute(select(IngestionState).where(IngestionState.symbol == "EURUSD"))
    fetched = result.scalar_one()
    assert fetched.symbol == "EURUSD"
    assert fetched.status == "idle"

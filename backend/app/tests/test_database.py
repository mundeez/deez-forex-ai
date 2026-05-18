"""Tests for database schema, constraints, and indexes."""

import pytest
from sqlalchemy import inspect
from app.database import engine, Base
from app import models


class TestSchema:
    @pytest.mark.asyncio
    async def test_all_tables_created(self, db_engine):
        """Ensure all model tables are present in the DB."""
        expected = {
            "market_data",
            "trades",
            "ai_decisions",
            "backtest_runs",
            "daily_pnl",
            "settings",
            "account_snapshots",
            "active_pairs",
            "market_state_snapshots",
            "pair_performance_by_hour",
        }
        actual = set(Base.metadata.tables.keys())
        assert expected.issubset(actual)

    @pytest.mark.asyncio
    async def test_market_data_indexes(self, db_engine):
        """Verify expected indexes exist on market_data table."""
        table = Base.metadata.tables["market_data"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_market_data_symbol" in index_names
        assert "ix_market_data_timestamp" in index_names

    @pytest.mark.asyncio
    async def test_trades_indexes(self, db_engine):
        """Verify expected indexes exist on trades table."""
        table = Base.metadata.tables["trades"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_trades_id" in index_names

    @pytest.mark.asyncio
    async def test_trade_enums_store_correctly(self, db_session):
        from app.enums import TradeDirection, TradeMode, TradeStatus, DataProvider
        trade = models.Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.OPEN,
            mode=TradeMode.PAPER,
            provider=DataProvider.METAAPI,
            entry_price=1.0850,
        )
        db_session.add(trade)
        await db_session.commit()
        await db_session.refresh(trade)
        assert trade.direction == TradeDirection.BUY
        assert trade.status == TradeStatus.OPEN
        assert trade.mode == TradeMode.PAPER
        assert trade.provider == DataProvider.METAAPI

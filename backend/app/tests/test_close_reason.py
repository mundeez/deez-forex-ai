"""Tests for close_reason persistence and learning-column population."""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from app.models import Trade, TradeStatus, TradeDirection
from app.enums import TradeMode, DataProvider
from app.services.execution.executor import ExecutionService


class TestCloseReason:
    @pytest.mark.asyncio
    async def test_close_trade_sets_close_reason(self, db_session):
        executor = ExecutionService()
        # Create a trade manually
        trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.OPEN,
            mode=TradeMode.PAPER,
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0900,
            position_size=0.01,
            open_time=datetime.utcnow() - timedelta(minutes=30),
            highest_price_seen=1.0880,
            lowest_price_seen=1.0830,
            provider=DataProvider.METAAPI,
        )
        db_session.add(trade)
        await db_session.commit()
        await db_session.refresh(trade)

        # Close it with a specific reason
        closed = await executor.close_trade(db_session, trade.id, 1.0900, close_reason="tp")
        await db_session.commit()
        await db_session.refresh(closed)

        assert closed.status == TradeStatus.CLOSED
        assert closed.close_reason == "tp"
        assert "Close reason: tp" in (closed.rationale or "")
        assert closed.exit_price == 1.0900
        assert closed.pnl is not None
        assert closed.actual_holding_min is not None
        assert closed.session_at_close is not None
        assert closed.mfe_pips is not None
        assert closed.mae_pips is not None

    @pytest.mark.asyncio
    async def test_close_all_positions_sets_eod_reason(self, db_session, monkeypatch):
        executor = ExecutionService()
        trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.OPEN,
            mode=TradeMode.PAPER,
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0900,
            position_size=0.01,
            open_time=datetime.utcnow() - timedelta(minutes=30),
            provider=DataProvider.METAAPI,
        )
        db_session.add(trade)
        await db_session.commit()

        # Mock price feed so close_all can find a price
        async def mock_price(sym):
            return {"bid": 1.0840, "ask": 1.0842}

        monkeypatch.setattr(
            "app.services.execution.executor.MetaApiClient.get_current_price",
            staticmethod(mock_price),
        )

        closed_list = await executor.close_all_open_positions(db_session, close_reason="eod")
        await db_session.commit()

        # Other tests may leave open trades in the shared in-memory DB.
        # Assert our trade is among those closed with the right reason.
        our_closed = [t for t in closed_list if t.id == trade.id]
        assert len(our_closed) == 1
        assert our_closed[0].close_reason == "eod"

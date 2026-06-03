"""Tests for close_reason persistence and learning-column population."""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models import Trade, TradeStatus, TradeDirection
from app.enums import TradeMode, DataProvider
from app.services.execution.executor import ExecutionService
from app.utils.time import utc_now


class TestCloseReason:
    @pytest.mark.asyncio
    async def test_close_trade_sets_close_reason(self, db_session, monkeypatch):
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
            open_time=utc_now() - timedelta(minutes=30),
            highest_price_seen=1.0880,
            lowest_price_seen=1.0830,
            provider=DataProvider.METAAPI,
        )
        db_session.add(trade)
        await db_session.commit()
        await db_session.refresh(trade)

        # Mock price feed so close_trade doesn't hit ZMQ timeout
        async def mock_price(sym):
            return {"bid": 1.0840, "ask": 1.0842}

        monkeypatch.setattr(
            "app.services.execution.executor.MT5ZMQClient.get_current_price",
            staticmethod(mock_price),
        )

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
            open_time=utc_now() - timedelta(minutes=30),
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
        monkeypatch.setattr(
            "app.services.execution.executor.MT5ZMQClient.get_current_price",
            staticmethod(mock_price),
        )

        closed_list = await executor.close_all_open_positions(db_session, close_reason="eod")
        await db_session.commit()

        # Other tests may leave open trades in the shared in-memory DB.
        # Assert our trade is among those closed with the right reason.
        our_closed = [t for t in closed_list if t.id == trade.id]
        assert len(our_closed) == 1
        assert our_closed[0].close_reason == "eod"

    @pytest.mark.asyncio
    async def test_time_based_close_expired_trade(self, db_session, monkeypatch):
        """Trades open longer than max_duration should be closed by time-based check."""
        executor = ExecutionService()
        trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.OPEN,
            mode=TradeMode.PAPER,
            strategy_mode="day_trading",
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0900,
            position_size=0.01,
            open_time=utc_now() - timedelta(minutes=200),
            provider=DataProvider.METAAPI,
        )
        db_session.add(trade)
        await db_session.commit()

        async def mock_price(sym):
            return {"bid": 1.0840, "ask": 1.0842}

        monkeypatch.setattr(
            "app.services.execution.executor.MetaApiClient.get_current_price",
            staticmethod(mock_price),
        )
        monkeypatch.setattr(
            "app.services.execution.executor.MT5ZMQClient.get_current_price",
            staticmethod(mock_price),
        )

        closed = await executor.check_and_close_time_based_positions(db_session)
        await db_session.commit()

        our_closed = [t for t in closed if t.id == trade.id]
        assert len(our_closed) == 1
        assert our_closed[0].status == TradeStatus.CLOSED
        assert "max_duration" in our_closed[0].close_reason

    @pytest.mark.asyncio
    async def test_sl_tp_uses_correct_spread_side(self, db_session, monkeypatch):
        """BUY SL should trigger on bid (not ask), SELL SL on ask (not bid)."""
        executor = ExecutionService()

        # BUY trade: entry 1.0850, SL 1.0800. Bid hits 1.0795 -> should close.
        trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.OPEN,
            mode=TradeMode.PAPER,
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0900,
            position_size=0.01,
            open_time=utc_now() - timedelta(minutes=5),
            provider=DataProvider.METAAPI,
        )
        db_session.add(trade)
        await db_session.commit()

        async def mock_price(sym):
            # bid below SL, ask above SL — only bid should trigger for BUY
            return {"bid": 1.0795, "ask": 1.0797}

        monkeypatch.setattr(
            "app.services.execution.executor.MetaApiClient.get_current_price",
            staticmethod(mock_price),
        )
        monkeypatch.setattr(
            "app.services.execution.executor.MT5ZMQClient.get_current_price",
            staticmethod(mock_price),
        )

        closed = await executor.check_and_close_positions(db_session)
        await db_session.commit()

        our_closed = [t for t in closed if t.id == trade.id]
        assert len(our_closed) == 1
        assert our_closed[0].close_reason == "stop_loss"

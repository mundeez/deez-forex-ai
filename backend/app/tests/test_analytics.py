"""Tests for the live portfolio analytics service."""

import pytest
import pytest_asyncio
from datetime import timedelta
from sqlalchemy import delete

from app.models import Trade, TradeStatus, TradeDirection
from app.enums import TradeMode, DataProvider
from app.services.analytics_service import compute_portfolio_metrics
from app.utils.time import utc_now


EQUITY_BALANCE = 100.0


@pytest_asyncio.fixture(autouse=True)
async def clean_trades(db_session):
    """Truncate trades before each test so metrics are deterministic."""
    await db_session.execute(delete(Trade))
    await db_session.commit()


async def _add_trades(db_session, pnls):
    """Helper to insert closed trades with ordered close_time."""
    base_time = utc_now() - timedelta(minutes=len(pnls) + 1)
    for i, pnl in enumerate(pnls):
        trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.CLOSED,
            mode=TradeMode.PAPER,
            entry_price=1.1000,
            exit_price=1.1000 + (pnl * 0.0001),
            stop_loss=1.0900,
            take_profit=1.1100,
            position_size=0.01,
            pnl=pnl,
            pnl_pct=pnl / 100.0,
            close_time=base_time + timedelta(minutes=i),
            open_time=base_time - timedelta(minutes=10),
            provider=DataProvider.METAAPI,
        )
        db_session.add(trade)
    await db_session.commit()


class TestPortfolioAnalytics:
    @pytest.mark.asyncio
    async def test_no_trades(self, db_session):
        metrics = await compute_portfolio_metrics(db_session, EQUITY_BALANCE)
        assert metrics["equity"] == EQUITY_BALANCE
        assert metrics["realized_pnl"] == 0.0
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] is None
        assert metrics["profit_factor"] is None
        assert metrics["expectancy"] is None
        assert metrics["equity_history"] == []

    @pytest.mark.asyncio
    async def test_all_winning_trades(self, db_session):
        await _add_trades(db_session, [10.0, 10.0, 10.0])
        metrics = await compute_portfolio_metrics(db_session, EQUITY_BALANCE)

        assert metrics["total_trades"] == 3
        assert metrics["winning_trades"] == 3
        assert metrics["losing_trades"] == 0
        assert metrics["win_rate"] == 100.0
        assert metrics["realized_pnl"] == 30.0
        assert metrics["equity"] == EQUITY_BALANCE + 30.0
        assert metrics["profit_factor"] is None  # no losses
        assert metrics["max_drawdown_pct"] == 0.0
        assert metrics["sharpe_ratio"] is not None
        assert metrics["expectancy"] == pytest.approx(10.0, rel=1e-3)
        assert len(metrics["equity_history"]) == 3

    @pytest.mark.asyncio
    async def test_all_losing_trades(self, db_session):
        await _add_trades(db_session, [-10.0, -10.0, -10.0])
        metrics = await compute_portfolio_metrics(db_session, EQUITY_BALANCE)

        assert metrics["total_trades"] == 3
        assert metrics["winning_trades"] == 0
        assert metrics["losing_trades"] == 3
        assert metrics["win_rate"] == 0.0
        assert metrics["realized_pnl"] == -30.0
        assert metrics["equity"] == EQUITY_BALANCE - 30.0
        assert metrics["profit_factor"] == 0.0
        assert metrics["max_drawdown_pct"] == pytest.approx(30.0 / EQUITY_BALANCE * 100, rel=1e-3)
        assert metrics["expectancy"] == pytest.approx(-10.0, rel=1e-3)

    @pytest.mark.asyncio
    async def test_mixed_trades(self, db_session):
        # Wins then losses to make drawdown deterministic.
        await _add_trades(db_session, [10.0, 10.0, -5.0, -5.0])
        metrics = await compute_portfolio_metrics(db_session, EQUITY_BALANCE)

        assert metrics["total_trades"] == 4
        assert metrics["winning_trades"] == 2
        assert metrics["losing_trades"] == 2
        assert metrics["win_rate"] == 50.0
        assert metrics["realized_pnl"] == 10.0
        assert metrics["equity"] == EQUITY_BALANCE + 10.0
        assert metrics["profit_factor"] == pytest.approx(20.0 / 10.0, rel=1e-3)
        # Peak 120 after two wins, trough 110 after losses
        assert metrics["max_drawdown_pct"] == pytest.approx((120.0 - 110.0) / 120.0 * 100, rel=1e-3)
        assert metrics["expectancy"] == pytest.approx(
            (10.0 * 0.5) - (5.0 * 0.5), rel=1e-3
        )

    @pytest.mark.asyncio
    async def test_portfolio_reset_filters_trades(self, db_session):
        old = utc_now() - timedelta(days=2)
        recent = utc_now() - timedelta(minutes=5)

        old_trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.CLOSED,
            mode=TradeMode.PAPER,
            entry_price=1.1000,
            exit_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1100,
            position_size=0.01,
            pnl=20.0,
            pnl_pct=20.0 / 100.0,
            close_time=old,
            open_time=old - timedelta(minutes=10),
            provider=DataProvider.METAAPI,
        )
        new_trade = Trade(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            status=TradeStatus.CLOSED,
            mode=TradeMode.PAPER,
            entry_price=1.1000,
            exit_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1100,
            position_size=0.01,
            pnl=-5.0,
            pnl_pct=-5.0 / 100.0,
            close_time=recent,
            open_time=recent - timedelta(minutes=10),
            provider=DataProvider.METAAPI,
        )
        db_session.add(old_trade)
        db_session.add(new_trade)
        await db_session.commit()

        reset_at = recent - timedelta(minutes=1)
        metrics = await compute_portfolio_metrics(db_session, EQUITY_BALANCE, reset_at)

        assert metrics["total_trades"] == 1
        assert metrics["realized_pnl"] == -5.0
        assert metrics["winning_trades"] == 0
        assert metrics["losing_trades"] == 1

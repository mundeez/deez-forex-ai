"""Sprint 5 unit tests — Backtesting + AI Exit Agent."""
import pytest
from datetime import datetime, timezone
from app.backtest.data_guard import DataLeakageGuard
from app.backtest.walk_forward import WalkForwardTester
from app.backtest.monte_carlo import MonteCarloSimulator
from app.backtest.regime_tester import RegimeBacktester


class TestDataLeakageGuard:
    def test_validate_monotonic_candles(self):
        candles = [
            {"timestamp": "2024-01-01T00:00:00", "close": 1.0},
            {"timestamp": "2024-01-01T00:01:00", "close": 1.1},
            {"timestamp": "2024-01-01T00:02:00", "close": 1.2},
        ]
        assert DataLeakageGuard.validate_candles(candles) is True

    def test_detects_non_monotonic(self):
        candles = [
            {"timestamp": "2024-01-01T00:02:00", "close": 1.2},
            {"timestamp": "2024-01-01T00:01:00", "close": 1.1},
        ]
        assert DataLeakageGuard.validate_candles(candles) is False


class TestWalkForwardTester:
    def test_run_with_sufficient_data(self):
        decisions = []
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(300):
            ts = base + __import__("datetime").timedelta(days=i)
            pnl = 10 if i % 3 == 0 else -5
            decisions.append({"timestamp": ts, "pnl": pnl, "direction": "buy"})

        results = WalkForwardTester.run(decisions, train_months=3, test_months=1)
        assert len(results) > 0
        for r in results:
            assert "profit_factor" in r
            assert "win_rate" in r
            assert "sharpe" in r

    def test_run_insufficient_data(self):
        results = WalkForwardTester.run([], train_months=6, test_months=1)
        assert results == []


class TestMonteCarloSimulator:
    def test_run_basic(self):
        returns = [10, -5, 8, -3, 12, -6, 15, -4, 9, -2]
        result = MonteCarloSimulator.run(returns, n_runs=1000, initial_equity=1000, ruin_threshold=700)
        assert result["n_runs"] == 1000
        assert 0 <= result["ruin_probability"] <= 1
        assert result["median_max_dd_pct"] <= 0

    def test_insufficient_returns(self):
        result = MonteCarloSimulator.run([5], n_runs=100)
        assert result == {}


class TestRegimeBacktester:
    def test_run_multiple_regimes(self):
        trades = [
            {"regime": "trending", "pnl": 100},
            {"regime": "trending", "pnl": 80},
            {"regime": "trending", "pnl": -40},
            {"regime": "ranging", "pnl": 20},
            {"regime": "ranging", "pnl": -30},
        ]
        results = RegimeBacktester.run(trades)
        assert "trending" in results
        assert "ranging" in results
        assert results["trending"]["count"] == 3
        assert results["ranging"]["count"] == 2

    def test_empty_trades(self):
        assert RegimeBacktester.run([]) == {}


class TestTradeManagerAgent:
    @pytest.mark.asyncio
    async def test_advise_returns_valid_structure(self):
        from app.ai.team.trade_manager import TradeManagerAgent
        tm = TradeManagerAgent()
        advice = await tm.advise(
            symbol="EURUSD",
            direction="buy",
            entry_price=1.0800,
            current_price=1.0820,
            stop_loss=1.0750,
            take_profit=1.0900,
            pnl=20.0,
            pnl_pct=0.5,
            duration_min=15,
            analysis_snapshot={"technical": {"timeframes": {"1m": {"indicators": {}}}}},
        )
        assert "action" in advice
        assert advice["action"] in ("HOLD", "CLOSE", "PARTIAL_CLOSE")
        assert "confidence" in advice
        assert "reasoning" in advice

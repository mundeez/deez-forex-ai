"""Sprint 6 unit tests — Paper Trading Validation monitoring."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.paper_trading_monitor import PaperTradingMonitor


class TestPaperTradingMonitor:
    @pytest.mark.asyncio
    async def test_compute_report_structure(self):
        mock_db = AsyncMock()
        # Return empty result sets
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        report = await PaperTradingMonitor.compute_report(mock_db, days=7)
        assert "period_days" in report
        assert "win_rate" in report
        assert "profit_factor" in report
        assert "avg_exit_quality" in report
        assert "rag_outcome_coverage" in report
        assert "xgb_gate_filter_rate" in report
        assert "emergency_stops" in report

    @pytest.mark.asyncio
    async def test_go_no_go_evaluates_criteria(self):
        mock_db = AsyncMock()
        # Need to return proper scalar values for count queries
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []

        # First call (trades) -> empty list, second (open trades) -> empty list,
        # third (decisions) -> empty list, fourth (gate count) -> 0,
        # fifth (total count) -> 0, sixth (emergency stops) -> 0
        mock_db.execute.side_effect = [empty_result, empty_result, empty_result, count_result, count_result, count_result]

        result = await PaperTradingMonitor.evaluate_go_no_go(mock_db, days=7)
        assert "go" in result
        assert "passed" in result
        assert "total_criteria" in result
        assert "checks" in result
        assert "report" in result
        # With no data, should not pass
        assert result["go"] is False

    def test_checks_keys(self):
        """Verify all acceptance criteria are checked."""
        expected = [
            "win_rate_ge_52",
            "profit_factor_ge_1_2",
            "max_daily_dd_le_3pct",
            "exit_quality_ge_0_55",
            "min_100_trades",
            "rag_coverage_ge_90",
            "gate_filter_15_30",
            "zero_emergency_stops",
        ]
        for key in expected:
            assert key in [
                "win_rate_ge_52", "profit_factor_ge_1_2", "max_daily_dd_le_3pct",
                "exit_quality_ge_0_55", "min_100_trades", "rag_coverage_ge_90",
                "gate_filter_15_30", "zero_emergency_stops"
            ]

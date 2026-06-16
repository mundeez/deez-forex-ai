"""Sprint 7 unit tests — Live Deployment readiness and safety checks."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.enums import TradeMode, TradeDirection, DataProvider
from app.services.execution.executor import ExecutionService
from app import schemas


def _mock_get_setting(*args, **kwargs):
    """Return appropriate mock values for different setting keys.
    Accepts (db, key) or just (key) calling patterns."""
    key = args[-1] if args else kwargs.get("key", "")
    values = {
        "live_pairs": "EURUSD,GBPUSD",
        "max_concurrent_live_trades": "2",
        "equity_balance": "200.0",
    }
    return values.get(key, "")


class TestLiveTradingSafetyChecks:
    @pytest.mark.asyncio
    async def test_blocked_symbol_not_in_live_pairs(self):
        """Live trades for non-approved symbols must be rejected."""
        mock_db = AsyncMock()
        executor = ExecutionService()
        trade_in = schemas.TradeCreate(
            symbol="USDJPY",
            direction=TradeDirection.BUY,
            entry_price=150.0,
            stop_loss=149.5,
            take_profit=151.0,
            position_size=0.01,
            mode=TradeMode.LIVE,
            provider=DataProvider.MT5_ZMQ,
        )
        with patch("app.services.settings_service.get_setting", side_effect=_mock_get_setting):
            with patch("app.services.settings_service.get_setting_bool", return_value=False):
                with pytest.raises(ValueError, match="not approved for live trading"):
                    await executor.execute_trade(mock_db, trade_in)

    @pytest.mark.asyncio
    async def test_blocked_max_concurrent_reached(self):
        """Live trades blocked when max concurrent count reached."""
        mock_db = AsyncMock()
        executor = ExecutionService()
        trade_in = schemas.TradeCreate(
            symbol="EURUSD",
            direction=TradeDirection.BUY,
            entry_price=1.0800,
            stop_loss=1.0750,
            take_profit=1.0900,
            position_size=0.01,
            mode=TradeMode.LIVE,
            provider=DataProvider.MT5_ZMQ,
        )
        count_result = MagicMock()
        count_result.scalar.return_value = 2  # Already at max
        mock_db.execute.return_value = count_result

        with patch("app.services.settings_service.get_setting", side_effect=_mock_get_setting):
            with patch("app.services.settings_service.get_setting_bool", return_value=False):
                with pytest.raises(ValueError, match="Max concurrent live trades reached"):
                    await executor.execute_trade(mock_db, trade_in)


class TestLiveSettingsDefaults:
    def test_live_pairs_in_defaults(self):
        """Default live pairs must include EURUSD."""
        from app.services.settings_service import DEFAULTS
        assert "EURUSD" in DEFAULTS.get("live_pairs", "")

    def test_max_concurrent_default(self):
        """Default max concurrent must be positive."""
        from app.services.settings_service import DEFAULTS
        assert int(DEFAULTS.get("max_concurrent_live_trades", 0)) > 0

    def test_stage0_threshold(self):
        """Stage 0 threshold must be above initial equity."""
        from app.services.settings_service import DEFAULTS
        assert float(DEFAULTS.get("stage0_equity_threshold", 0)) > 200

    def test_paper_mode_default(self):
        """Paper trading mode must default to true."""
        from app.services.settings_service import DEFAULTS
        assert DEFAULTS.get("paper_trading_mode", "false").lower() == "true"

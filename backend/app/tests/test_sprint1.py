"""Sprint 1 unit tests — P0 fixes + data foundation."""
import pytest
from unittest.mock import AsyncMock, patch
from app.services.risk.manager import RiskManager
from app.services.regime_detector import RegimeDetector


class TestPositionSizing:
    def test_micro_lot_floor_standard_pair(self):
        rm = RiskManager()
        size = rm.calculate_position_size(200, 1.0, 1.0850, 1.0800, "EURUSD")
        assert size >= 0.01, f"Expected >= 0.01, got {size}"

    def test_micro_lot_floor_jpy_pair(self):
        rm = RiskManager()
        size = rm.calculate_position_size(200, 1.0, 150.00, 149.50, "USDJPY")
        assert size >= 0.01, f"Expected >= 0.01, got {size}"

    def test_larger_account_capped_by_max_size(self):
        rm = RiskManager()
        # raw_size = 100 / 500 = 0.20, but max_size cap applies
        size = rm.calculate_position_size(10000, 1.0, 1.0850, 1.0800, "EURUSD")
        assert size == 0.02, f"Expected 0.02 (capped), got {size}"

    def test_larger_account_uncapped(self):
        rm = RiskManager()
        size = rm.calculate_position_size(10000, 10.0, 1.0850, 1.0800, "EURUSD")
        assert size == 0.02, f"Expected 0.02, got {size}"


class TestRegimeDetector:
    def test_trending_regime(self):
        tech = {
            "timeframes": {
                "1h": {
                    "indicators": {"adx_14": 30, "bb_upper": 1.09, "bb_lower": 1.08, "close": 1.085},
                    "signal": "bullish",
                    "bb_squeeze": False,
                }
            }
        }
        result = RegimeDetector.detect(tech, "EURUSD")
        assert result["regime"] == "trending"
        assert result["confidence"] > 0.5

    def test_ranging_regime(self):
        close = 1.085
        tech = {
            "timeframes": {
                "1h": {
                    "indicators": {
                        "adx_14": 15,
                        "bb_upper": close + 0.0007,   # ~0.13% width
                        "bb_lower": close - 0.0007,
                        "close": close,
                    },
                    "signal": "neutral",
                    "bb_squeeze": True,
                }
            }
        }
        result = RegimeDetector.detect(tech, "EURUSD")
        assert result["regime"] == "ranging"

    def test_breakout_regime(self):
        tech = {
            "timeframes": {
                "1h": {
                    "indicators": {"adx_14": 30, "bb_upper": 1.0851, "bb_lower": 1.0849, "close": 1.085},
                    "signal": "bullish",
                    "bb_squeeze": True,
                }
            }
        }
        result = RegimeDetector.detect(tech, "EURUSD")
        assert result["regime"] == "breakout"


class TestEmergencyStops:
    @pytest.mark.asyncio
    async def test_emergency_stops_bypass_unfunded_account(self):
        """Emergency stops should not fire when equity_balance < 150 (test env)."""
        rm = RiskManager()
        mock_db = AsyncMock()
        rm._get_equity = AsyncMock(return_value=100.0)
        with patch("app.services.risk.manager.get_setting_float", return_value=100.0):
            ok, reason = await rm.validate_emergency_stops(mock_db)
        assert ok is True, f"Expected OK for unfunded account, got: {reason}"

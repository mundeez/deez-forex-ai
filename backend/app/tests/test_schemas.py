"""Tests for Pydantic schemas and validators."""

import pytest
from pydantic import ValidationError
from app.schemas import TradeCreate, AppSettingsUpdate, ManualTradeCreate
from app.enums import TradeDirection, TradeMode, DataProvider


class TestTradeCreate:
    def test_valid_trade(self):
        trade = TradeCreate(
            symbol="eurusd",
            direction=TradeDirection.BUY,
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0900,
            risk_pct=1.5,
        )
        assert trade.symbol == "EURUSD"  # uppercase validator
        assert trade.direction == TradeDirection.BUY
        assert trade.stop_loss == 1.08  # precision rounded to 5 decimals
        assert trade.mode == TradeMode.PAPER

    def test_symbol_uppercased(self):
        trade = TradeCreate(symbol="gbpusd", direction=TradeDirection.SELL)
        assert trade.symbol == "GBPUSD"

    def test_invalid_direction(self):
        with pytest.raises(ValidationError):
            TradeCreate(symbol="EURUSD", direction="invalid")

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            TradeCreate(symbol="EURUSD", direction=TradeDirection.BUY, entry_price=-1.0)

    def test_risk_pct_bounds(self):
        with pytest.raises(ValidationError):
            TradeCreate(symbol="EURUSD", direction=TradeDirection.BUY, risk_pct=150.0)

    def test_default_provider(self):
        trade = TradeCreate(symbol="EURUSD", direction=TradeDirection.BUY)
        assert trade.provider == DataProvider.METAAPI


class TestAppSettingsUpdate:
    def test_valid_risk_settings(self):
        settings = AppSettingsUpdate(max_risk_per_trade_pct=2.5, max_daily_loss_pct=5.0)
        assert settings.max_risk_per_trade_pct == 2.5

    def test_risk_pct_too_high(self):
        with pytest.raises(ValidationError):
            AppSettingsUpdate(max_risk_per_trade_pct=100.0)

    def test_risk_pct_too_low(self):
        with pytest.raises(ValidationError):
            AppSettingsUpdate(max_risk_per_trade_pct=0.0)

    def test_ai_confidence_bounds(self):
        with pytest.raises(ValidationError):
            AppSettingsUpdate(ai_confidence_threshold=1.5)

    def test_max_open_per_symbol_bounds(self):
        with pytest.raises(ValidationError):
            AppSettingsUpdate(max_open_per_symbol=0)
        with pytest.raises(ValidationError):
            AppSettingsUpdate(max_open_per_symbol=25)

    def test_chart_refresh_bounds(self):
        with pytest.raises(ValidationError):
            AppSettingsUpdate(chart_refresh_ms=50)
        with pytest.raises(ValidationError):
            AppSettingsUpdate(chart_refresh_ms=100000)


class TestManualTradeCreate:
    def test_valid_manual_trade(self):
        trade = ManualTradeCreate(symbol="USDJPY", direction="buy")
        assert trade.symbol == "USDJPY"
        assert trade.direction == "buy"

    def test_optional_fields(self):
        trade = ManualTradeCreate(symbol="EURUSD", direction="sell")
        assert trade.entry_price is None
        assert trade.mode == "paper"

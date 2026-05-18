"""Tests for consolidated domain enums."""

import pytest
from app.enums import TradeStatus, TradeDirection, TradeMode, DataProvider, StrategyMode


class TestTradeStatus:
    def test_members(self):
        assert TradeStatus.PENDING == "pending"
        assert TradeStatus.OPEN == "open"
        assert TradeStatus.CLOSED == "closed"
        assert TradeStatus.CANCELLED == "cancelled"

    def test_string_comparison(self):
        assert TradeStatus.OPEN == "open"
        assert "open" == TradeStatus.OPEN


class TestTradeDirection:
    def test_members(self):
        assert TradeDirection.BUY == "buy"
        assert TradeDirection.SELL == "sell"

    def test_from_string(self):
        assert TradeDirection("buy") == TradeDirection.BUY
        assert TradeDirection("sell") == TradeDirection.SELL

    def test_invalid_direction(self):
        with pytest.raises(ValueError):
            TradeDirection("invalid")


class TestTradeMode:
    def test_members(self):
        assert TradeMode.PAPER == "paper"
        assert TradeMode.LIVE == "live"


class TestDataProvider:
    def test_members(self):
        assert DataProvider.METAAPI == "metaapi"
        assert DataProvider.MT5_ZMQ == "mt5_zmq"


class TestStrategyMode:
    def test_members(self):
        assert StrategyMode.SCALPING == "scalping"
        assert StrategyMode.DAY_TRADING == "day_trading"
        assert StrategyMode.SWING == "swing"

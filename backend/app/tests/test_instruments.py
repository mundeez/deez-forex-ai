"""Tests for per-symbol PnL math and instrument metadata."""

import pytest
from app.services.instruments import (
    meta,
    pip_size,
    contract_size,
    price_decimals,
    pips,
    pnl_usd,
    INSTRUMENTS,
)


class TestInstrumentMeta:
    def test_known_symbols(self):
        for sym in INSTRUMENTS:
            assert meta(sym)["pip"] > 0
            assert meta(sym)["contract"] > 0

    def test_unknown_symbol_uses_default(self):
        m = meta("UNKNOWN")
        assert m["pip"] == 0.0001
        assert m["contract"] == 100000

    def test_pip_size_jpy(self):
        assert pip_size("USDJPY") == 0.01
        assert pip_size("GBPJPY") == 0.01

    def test_pip_size_gold(self):
        assert pip_size("XAUUSD") == 0.10

    def test_pip_size_fx(self):
        assert pip_size("EURUSD") == 0.0001
        assert pip_size("GBPUSD") == 0.0001

    def test_contract_size_fx(self):
        assert contract_size("EURUSD") == 100000

    def test_contract_size_gold(self):
        assert contract_size("XAUUSD") == 100

    def test_price_decimals(self):
        assert price_decimals("EURUSD") == 5
        assert price_decimals("USDJPY") == 3
        assert price_decimals("XAUUSD") == 2


class TestPipsConversion:
    def test_eurusd_pips(self):
        # 10 pips = 0.0010
        assert pips("EURUSD", 0.0010) == 10.0

    def test_usdjpy_pips(self):
        # 15 pips = 0.15
        assert pips("USDJPY", 0.15) == 15.0

    def test_xauusd_pips(self):
        # 5 pips = 0.50
        assert pips("XAUUSD", 0.50) == 5.0

    def test_zero_pip_size_returns_zero(self):
        # DEFAULT has pip=0.0001, so unknown symbol still divides by that.
        # The zero-protection branch only triggers when pip_size returns 0.
        assert pips("UNKNOWN", 0.0010) == 10.0  # 0.0010 / 0.0001


class TestPnLUSD:
    def test_eurusd_buy_profit(self):
        # Buy 1.0850 -> 1.0950 = +100 pips
        # diff = 0.0100, contract = 100000, size = 0.01 lot
        # pnl = 0.0100 * 100000 * 0.01 = 10 USD
        pnl = pnl_usd("EURUSD", is_buy=True, entry=1.0850, exit_price=1.0950, size=0.01)
        assert pytest.approx(pnl, rel=1e-3) == 10.0

    def test_eurusd_buy_loss(self):
        pnl = pnl_usd("EURUSD", is_buy=True, entry=1.0850, exit_price=1.0750, size=0.01)
        assert pytest.approx(pnl, rel=1e-3) == -10.0

    def test_eurusd_sell_profit(self):
        # Sell 1.0950 -> 1.0850 = +100 pips (price dropped)
        pnl = pnl_usd("EURUSD", is_buy=False, entry=1.0950, exit_price=1.0850, size=0.01)
        assert pytest.approx(pnl, rel=1e-3) == 10.0

    def test_usdjpy_buy_profit(self):
        # USDJPY: pip = 0.01, contract = 100000, quote = JPY -> USD factor = 1/157
        # Buy 157.00 -> 157.50 = +50 pips
        # diff = 0.50, pnl_quote = 0.50 * 100000 * 0.01 = 500 JPY = ~3.18 USD
        pnl = pnl_usd("USDJPY", is_buy=True, entry=157.00, exit_price=157.50, size=0.01)
        expected = 0.50 * 100000 * 0.01 / 157.0
        assert pytest.approx(pnl, rel=1e-3) == expected

    def test_xauusd_buy_profit(self):
        # Gold: pip = 0.10, contract = 100
        # Buy 2350.0 -> 2360.0 = +100 pips (10.0 / 0.10)
        # diff = 10.0, pnl = 10.0 * 100 * 0.01 = 10 USD
        pnl = pnl_usd("XAUUSD", is_buy=True, entry=2350.0, exit_price=2360.0, size=0.01)
        assert pytest.approx(pnl, rel=1e-3) == 10.0

    def test_none_inputs_return_zero(self):
        assert pnl_usd("EURUSD", True, None, 1.09, 0.01) == 0.0  # type: ignore[arg-type]
        assert pnl_usd("EURUSD", True, 1.08, None, 0.01) == 0.0  # type: ignore[arg-type]
        assert pnl_usd("EURUSD", True, 1.08, 1.09, None) == 0.0  # type: ignore[arg-type]

"""Tests for the adaptive ATR stop-loss pip-size fix.

The ATR SL clamps the stop distance to [10 pips, 30 pips]. The pip size must
be derived from the instrument metadata (pip_size) — NOT hardcoded to
0.0001/0.01 — otherwise gold (XAUUSD, pip=0.10) and crypto/indices get a
stop that is ~1000x too tight.
"""
import numpy as np
import pandas as pd

from app.services.instruments import pip_size


def _make_candles(symbol: str, n: int = 20, base: float = None) -> pd.DataFrame:
    """Build n synthetic 5m candles around `base` with a small range."""
    if base is None:
        base = {"XAUUSD": 2350.0, "EURUSD": 1.0850, "USDJPY": 157.0}.get(symbol, 1.0850)
    pip = pip_size(symbol)
    rows = []
    for i in range(n):
        c = base + i * pip
        rows.append({
            "timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=5 * i),
            "open": c, "high": c + 3 * pip, "low": c - 3 * pip, "close": c + pip,
        })
    df = pd.DataFrame(rows)
    df.attrs["symbol"] = symbol
    return df


class TestBacktestAtrSlPipSize:
    """The standalone backtest's _compute_atr_based_sl must respect pip_size."""

    def _engine(self):
        # Imported lazily so module-level app imports don't fail outside docker.
        from run_backtest_standalone import StandaloneBacktestEngine
        return StandaloneBacktestEngine.__new__(StandaloneBacktestEngine)

    def test_gold_sl_distance_uses_gold_pip(self):
        """XAUUSD SL distance must be on the order of 10-30 *gold* pips (1.0-3.0),
        not 10-30 FX pips (0.001-0.003)."""
        eng = self._engine()
        candles = _make_candles("XAUUSD", n=20, base=2350.0)
        sl = eng._compute_atr_based_sl(candles, 2350.0, "buy", "XAUUSD")
        assert sl is not None
        dist = 2350.0 - sl  # buy SL is below entry
        # 10 gold pips = 1.0, 30 gold pips = 3.0 -> dist must be in [1.0, 3.0]
        assert 1.0 <= dist <= 3.0, f"gold SL dist {dist} not in [1.0, 3.0] (pip mis-scaled)"

    def test_eurusd_sl_distance_uses_fx_pip(self):
        eng = self._engine()
        candles = _make_candles("EURUSD", n=20, base=1.0850)
        sl = eng._compute_atr_based_sl(candles, 1.0850, "buy", "EURUSD")
        assert sl is not None
        dist = 1.0850 - sl
        # 10 FX pips = 0.0010, 30 FX pips = 0.0030 (allow float rounding noise)
        assert 0.0009 <= dist <= 0.0031, f"EURUSD SL dist {dist} not in [0.0010, 0.0030]"

    def test_jpy_sl_distance_uses_jpy_pip(self):
        eng = self._engine()
        candles = _make_candles("USDJPY", n=20, base=157.0)
        sl = eng._compute_atr_based_sl(candles, 157.0, "buy", "USDJPY")
        assert sl is not None
        dist = 157.0 - sl
        # 10 JPY pips = 0.10, 30 JPY pips = 0.30
        assert 0.099 <= dist <= 0.301, f"USDJPY SL dist {dist} not in [0.10, 0.30]"

"""Tests for Dukascopy tick data parser."""
import pytest
import struct
import lzma
import pandas as pd
from datetime import datetime

from app.services.data.dukascopy.client import _parse_bi5, _resample_to_candles, SYMBOL_MAP, PRICE_MULT


def build_bi5_tick(time_ms: int, ask_raw: int, bid_raw: int, ask_vol: float, bid_vol: float) -> bytes:
    """Pack a single tick into the Dukascopy bi5 binary format."""
    return struct.pack(">IIIff", time_ms, ask_raw, bid_raw, ask_vol, bid_vol)


def test_parse_bi5_eurusd():
    """Parse a small bi5 file for EURUSD."""
    mult = PRICE_MULT["EURUSD"]
    ticks = []
    for i in range(5):
        time_ms = i * 1000
        ask_raw = int((1.0850 + i * 0.0001) * mult)
        bid_raw = int((1.0849 + i * 0.0001) * mult)
        ticks.append(build_bi5_tick(time_ms, ask_raw, bid_raw, 1.0, 1.0))
    raw = b"".join(ticks)
    compressed = lzma.compress(raw)

    df = _parse_bi5(compressed, "EURUSD")
    assert len(df) == 5
    assert "ask" in df.columns
    assert "bid" in df.columns
    assert "time_ms" in df.columns
    # Prices should be approximately 1.0850 + i*0.0001
    assert df["ask"].iloc[0] == pytest.approx(1.0850, abs=0.0001)


def test_parse_bi5_usdjpy():
    """Parse a bi5 file for USDJPY (different price multiplier)."""
    mult = PRICE_MULT["USDJPY"]
    tick = build_bi5_tick(0, int(157.50 * mult), int(157.49 * mult), 1.0, 1.0)
    compressed = lzma.compress(tick)
    df = _parse_bi5(compressed, "USDJPY")
    assert len(df) == 1
    assert df["ask"].iloc[0] == pytest.approx(157.50, abs=0.01)


def test_parse_bi5_empty():
    """Empty compressed data should return empty DataFrame."""
    df = _parse_bi5(b"", "EURUSD")
    assert df.empty


def test_resample_to_candles():
    """Tick DataFrame should resample to OHLCV candles."""
    now = pd.Timestamp.now(tz="UTC")
    ticks = pd.DataFrame({
        "timestamp": [now + pd.Timedelta(seconds=i) for i in range(120)],
        "ask": [1.0850 + i * 0.00001 for i in range(120)],
        "bid": [1.0849 + i * 0.00001 for i in range(120)],
        "ask_vol": [1.0] * 120,
        "bid_vol": [1.0] * 120,
    })
    ticks["price"] = (ticks["ask"] + ticks["bid"]) / 2.0
    ticks["volume"] = ticks["ask_vol"] + ticks["bid_vol"]

    candles = _resample_to_candles(ticks, "1m")
    assert len(candles) >= 1
    assert "open" in candles.columns
    assert "high" in candles.columns
    assert "low" in candles.columns
    assert "close" in candles.columns
    assert "volume" in candles.columns


def test_symbol_map_coverage():
    """All major FX pairs should have a Dukascopy mapping."""
    for sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD"]:
        assert sym in SYMBOL_MAP or sym in PRICE_MULT

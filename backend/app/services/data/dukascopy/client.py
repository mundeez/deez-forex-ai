"""Dukascopy free tick data downloader and local store.

Downloads .bi5 (LZMA) tick files from Dukascopy's public data feed,
decompresses, parses the binary format, resamples to candles, and stores
locally (Parquet on disk + index in Postgres).

URL format:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

Binary format (20 bytes per tick):
  time_offset_ms : uint32  (4 bytes) — milliseconds since hour start
  ask_price      : uint32  (4 bytes) — ask * 10^5 (or 10^3 for JPY, 10^2 for gold)
  bid_price      : uint32  (4 bytes) — bid * 10^5 (or 10^3 for JPY, 10^2 for gold)
  ask_volume     : float32 (4 bytes)
  bid_volume     : float32 (4 bytes)

Symbol mapping (Dukascopy ↔ our symbols):
  EURUSD → EURUSD
  GBPUSD → GBPUSD
  USDJPY → USDJPY
  BTCUSD → BTCUSD
  US30   → USA30IDXUSD (or similar Dukascopy CFD code)
"""
import lzma
import struct
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from io import BytesIO

import httpx
import pandas as pd

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.data.dukascopy")

BASE_URL = "https://datafeed.dukascopy.com/datafeed"

# Dukascopy symbol mapping (our symbol -> Dukascopy symbol)
SYMBOL_MAP = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "USDCAD": "USDCAD",
    "USDCHF": "USDCHF",
    "NZDUSD": "NZDUSD",
    "EURGBP": "EURGBP",
    "GBPJPY": "GBPJPY",
    "XAUUSD": "XAUUSD",
    "BTCUSD": "BTCUSD",
    # Indices (CFD) — Dukascopy codes may differ; these are best-effort
    "US30": "USA30IDXUSD",
    "NAS100": "USATECHIDXUSD",
    "SPX500": "US500IDXUSD",
}

# Price precision multiplier per symbol
PRICE_MULT = {
    "EURUSD": 1e5, "GBPUSD": 1e5, "AUDUSD": 1e5, "USDCAD": 1e5,
    "USDCHF": 1e5, "NZDUSD": 1e5, "EURGBP": 1e5,
    "USDJPY": 1e3, "GBPJPY": 1e3,
    "XAUUSD": 1e2,
    "BTCUSD": 1e2,
    "US30": 1e2, "NAS100": 1e2, "SPX500": 1e2,
}


def _dukascopy_symbol(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol)


def _price_mult(symbol: str) -> float:
    return PRICE_MULT.get(symbol, 1e5)


def _download_hour(symbol: str, dt: datetime) -> Optional[bytes]:
    """Download a single hour of tick data from Dukascopy."""
    d_symbol = _dukascopy_symbol(symbol)
    url = (
        f"{BASE_URL}/{d_symbol}/"
        f"{dt.year:04d}/"
        f"{dt.month:02d}/"
        f"{dt.day:02d}/"
        f"{dt.hour:02d}h_ticks.bi5"
    )
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url)
            if resp.status_code == 404:
                logger.debug("Dukascopy 404 for %s @ %s", symbol, dt.isoformat())
                return None
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            logger.warning("Dukascopy HTTP error for %s @ %s: %s", symbol, dt, exc)
        return None
    except Exception as exc:
        logger.warning("Dukascopy download error for %s @ %s: %s", symbol, dt, exc)
        return None


def _parse_bi5(data: bytes, symbol: str) -> pd.DataFrame:
    """Decompress LZMA and parse binary tick data into a DataFrame."""
    if not data:
        return pd.DataFrame()
    mult = _price_mult(symbol)
    try:
        decompressed = lzma.decompress(data)
    except lzma.LZMAError:
        # Try without header/footer (Dukascopy uses raw LZMA streams)
        try:
            decompressed = lzma.decompress(data, format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1}])
        except (lzma.LZMAError, ValueError):
            logger.warning("Failed to decompress LZMA data for %s", symbol)
            return pd.DataFrame()

    # Each tick is 20 bytes
    tick_size = 20
    n_ticks = len(decompressed) // tick_size
    records = []
    fmt = ">IIIff"  # big-endian: uint32, uint32, uint32, float32, float32

    for i in range(n_ticks):
        offset = i * tick_size
        chunk = decompressed[offset:offset + tick_size]
        if len(chunk) < tick_size:
            break
        time_ms, ask_raw, bid_raw, ask_vol, bid_vol = struct.unpack(fmt, chunk)
        records.append({
            "time_ms": int(time_ms),
            "ask": float(ask_raw) / mult,
            "bid": float(bid_raw) / mult,
            "ask_vol": float(ask_vol),
            "bid_vol": float(bid_vol),
        })

    return pd.DataFrame(records)


def _resample_to_candles(ticks: pd.DataFrame, timeframe: str = "1m") -> pd.DataFrame:
    """Resample tick DataFrame to OHLCV candles."""
    if ticks.empty:
        return pd.DataFrame()

    # Use mid price
    ticks["price"] = (ticks["ask"] + ticks["bid"]) / 2.0
    ticks["volume"] = ticks["ask_vol"] + ticks["bid_vol"]

    # Group by timeframe
    freq_map = {
        "1m": "1min", "5m": "5min", "15m": "15min",
        "1h": "1H", "4h": "4H", "1d": "1D",
    }
    freq = freq_map.get(timeframe, "1min")

    candles = ticks.resample(freq, on="timestamp").agg({
        "price": ["first", "max", "min", "last"],
        "volume": "sum",
    })
    candles.columns = ["open", "high", "low", "close", "volume"]
    candles = candles.dropna()
    return candles


class DukascopyClient:
    """Download and store historical tick/candle data from Dukascopy."""

    def __init__(self):
        self.base_url = BASE_URL

    async def download_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        """Download tick data for a date range and resample to candles."""
        all_ticks = []
        current = start.replace(minute=0, second=0, microsecond=0)
        end_hour = end.replace(minute=0, second=0, microsecond=0)

        while current <= end_hour:
            raw = _download_hour(symbol, current)
            if raw:
                df = _parse_bi5(raw, symbol)
                if not df.empty:
                    # Convert time_ms (offset from hour start) to absolute timestamp
                    df["timestamp"] = current + pd.to_timedelta(df["time_ms"], unit="ms")
                    all_ticks.append(df)
            current += timedelta(hours=1)

        if not all_ticks:
            logger.warning("No tick data downloaded for %s %s to %s", symbol, start, end)
            return pd.DataFrame()

        combined = pd.concat(all_ticks, ignore_index=True)
        combined = combined.sort_values("timestamp")
        return _resample_to_candles(combined, timeframe)

    async def store_candles(
        self,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame,
        db_session=None,
    ) -> int:
        """Store candles to Postgres historical_candles table."""
        if candles.empty:
            return 0
        from app import models
        count = 0
        for ts, row in candles.iterrows():
            if db_session is None:
                break
            candle = models.HistoricalCandle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row.get("volume", 0)),
                source="dukascopy",
            )
            db_session.add(candle)
            count += 1
            if count % 1000 == 0:
                await db_session.commit()
        if db_session and count % 1000 != 0:
            await db_session.commit()
        return count

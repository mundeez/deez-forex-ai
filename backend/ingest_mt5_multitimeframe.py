#!/usr/bin/env python3
"""Ingest multi-timeframe candles from MT5 ZMQ into historical_candles table."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_celery_session
from app.services.data.mt5_zmq_client import MT5ZMQClient

logger = logging.getLogger("ingest_multitimeframe")
logging.basicConfig(level=logging.INFO)

ACTIVE_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "GBPJPY",
]

TIMEFRAMES = {
    "1m": 50000,   # ~34 days
    "5m": 50000,   # ~246 days (8 months)
    "15m": 50000,  # ~737 days (2 years)
}


async def ingest_symbol_timeframe(
    db: AsyncSession,
    client: MT5ZMQClient,
    symbol: str,
    timeframe: str,
    limit: int,
) -> int:
    """Fetch candles from MT5 and upsert into historical_candles."""
    try:
        candles = await client.get_historical_candles(symbol, timeframe, limit=limit)
    except Exception as exc:
        logger.error("%s %s fetch failed: %s", symbol, timeframe, exc)
        return 0

    if not candles:
        logger.warning("%s %s: no candles returned", symbol, timeframe)
        return 0

    # Prepare upsert data
    rows = []
    for c in candles:
        rows.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": datetime.fromtimestamp(c["timestamp"] / 1000, tz=timezone.utc),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": int(c["volume"]),
            "source": "mt5_zmq",
        })

    stmt = text("""
        INSERT INTO historical_candles (symbol, timeframe, timestamp, open, high, low, close, volume, source)
        VALUES (:symbol, :timeframe, :timestamp, :open, :high, :low, :close, :volume, :source)
        ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            source = EXCLUDED.source
    """)

    count = 0
    for row in rows:
        try:
            await db.execute(stmt, row)
            count += 1
        except Exception as exc:
            logger.debug("Upsert skip %s %s %s: %s", symbol, timeframe, row["timestamp"], exc)

    await db.commit()
    logger.info("%s %s: upserted %d/%d candles", symbol, timeframe, count, len(candles))
    return count


async def main():
    client = MT5ZMQClient()
    total = 0

    async with get_celery_session()() as db:
        for symbol in ACTIVE_SYMBOLS:
            for tf, limit in TIMEFRAMES.items():
                count = await ingest_symbol_timeframe(db, client, symbol, tf, limit)
                total += count

    logger.info("Total candles upserted: %d", total)


if __name__ == "__main__":
    asyncio.run(main())

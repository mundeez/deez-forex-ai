"""MarketDataService: query bars from TimescaleDB continuous aggregates.

v0.8.0 M3 — Replaces direct market_data table queries with cagg-backed bars.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import text

from app.database import AsyncSessionLocal

logger = logging.getLogger("app.services.data.market_data")

# Cagg view names per timeframe
_CAGG_MAP = {
    "1m": "bars_1m",
    "5m": "bars_5m",
    "15m": "bars_15m",
    "1h": "bars_1h",
    "4h": "bars_4h",
    "1d": "bars_1d",
    "1w": "bars_1w",
}


class MarketDataService:
    """Query OHLC bars from TimescaleDB continuous aggregates or fallback tables."""

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1h",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Fetch bars for a symbol+timeframe from the appropriate continuous aggregate.
        Falls back to the `bars` hypertable if cagg doesn't exist (e.g., on SQLite).
        """
        start = start or (datetime.now(timezone.utc) - timedelta(days=30))
        end = end or datetime.now(timezone.utc)

        cagg_name = _CAGG_MAP.get(timeframe)
        if cagg_name is None:
            logger.warning("Unknown timeframe %s, defaulting to 1h", timeframe)
            cagg_name = "bars_1h"

        async with AsyncSessionLocal() as session:
            # Detect if we're on PostgreSQL/TimescaleDB
            db_type = await self._get_db_type(session)
            if db_type == "postgresql" and await self._cagg_exists(session, cagg_name):
                return await self._query_cagg(session, cagg_name, symbol, start, end, limit)
            else:
                return await self._query_fallback(session, symbol, timeframe, start, end, limit)

    async def _query_cagg(
        self,
        session,
        cagg_name: str,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Query a continuous aggregate view."""
        result = await session.execute(
            text(f"""
                SELECT bucket, open, high, low, close, avg_spread, tick_count
                FROM {cagg_name}
                WHERE symbol = :symbol
                  AND bucket BETWEEN :start AND :end
                ORDER BY bucket DESC
                LIMIT :limit
            """),
            {"symbol": symbol, "start": start, "end": end, "limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "timestamp": row[0].isoformat() if row[0] else None,
                "open": float(row[1]) if row[1] is not None else None,
                "high": float(row[2]) if row[2] is not None else None,
                "low": float(row[3]) if row[3] is not None else None,
                "close": float(row[4]) if row[4] is not None else None,
                "avg_spread": float(row[5]) if row[5] is not None else None,
                "tick_count": int(row[6]) if row[6] is not None else 0,
            }
            for row in rows
        ]

    async def _query_fallback(
        self,
        session,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Fallback to the bars hypertable or market_data table."""
        # First try bars hypertable
        try:
            result = await session.execute(
                text("""
                    SELECT timestamp, open, high, low, close, avg_spread, volume
                    FROM bars
                    WHERE symbol = :symbol
                      AND timeframe = :timeframe
                      AND timestamp BETWEEN :start AND :end
                    ORDER BY timestamp DESC
                    LIMIT :limit
                """),
                {"symbol": symbol, "timeframe": timeframe, "start": start, "end": end, "limit": limit},
            )
            rows = result.fetchall()
        except Exception:
            rows = []
        if rows:
            return [
                {
                    "timestamp": row[0].isoformat() if row[0] else None,
                    "open": float(row[1]) if row[1] is not None else None,
                    "high": float(row[2]) if row[2] is not None else None,
                    "low": float(row[3]) if row[3] is not None else None,
                    "close": float(row[4]) if row[4] is not None else None,
                    "avg_spread": float(row[5]) if row[5] is not None else None,
                    "tick_count": int(row[6]) if row[6] is not None else 0,
                }
                for row in rows
            ]

        # Final fallback to legacy market_data
        try:
            result = await session.execute(
                text("""
                    SELECT timestamp, open, high, low, close, volume
                    FROM market_data
                    WHERE symbol = :symbol
                      AND timeframe = :timeframe
                      AND timestamp BETWEEN :start AND :end
                    ORDER BY timestamp DESC
                    LIMIT :limit
                """),
                {"symbol": symbol, "timeframe": timeframe, "start": start, "end": end, "limit": limit},
            )
            rows = result.fetchall()
        except Exception:
            rows = []
        return [
            {
                "timestamp": row[0].isoformat() if row[0] else None,
                "open": float(row[1]) if row[1] is not None else None,
                "high": float(row[2]) if row[2] is not None else None,
                "low": float(row[3]) if row[3] is not None else None,
                "close": float(row[4]) if row[4] is not None else None,
                "avg_spread": None,
                "tick_count": 0,
            }
            for row in rows
        ]

    async def _get_db_type(self, session) -> str:
        result = await session.execute(text("SELECT 1"))
        # Check dialect via bind
        dialect = session.bind.dialect.name if session.bind else "unknown"
        return dialect

    async def _cagg_exists(self, session, cagg_name: str) -> bool:
        """Check if a continuous aggregate view exists."""
        result = await session.execute(
            text("""
                SELECT 1 FROM timescaledb_information.continuous_aggregates
                WHERE view_name = :name
            """),
            {"name": cagg_name},
        )
        return result.fetchone() is not None

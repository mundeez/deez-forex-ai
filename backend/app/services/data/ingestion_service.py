"""IngestionService: bulk tick ingestion, gap detection, backfill.

v0.8.0 M1 — Dukascopy primary historical source.
"""
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal as _DefaultAsyncSessionLocal, get_celery_session
from app.models import Tick, IngestionState
from app.services.data.dukascopy.client import _download_hour, _parse_bi5, _price_mult

logger = logging.getLogger("app.services.data.ingestion")

# Active symbols for historical ingestion
ACTIVE_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD",
]

# Dukascopy rate limit: max concurrent downloads
_MAX_CONCURRENT_DUKA = 4


def _hour_generator(start: datetime, end: datetime):
    """Yield every hour boundary between start and end (inclusive)."""
    current = start.replace(minute=0, second=0, microsecond=0)
    end_hour = end.replace(minute=0, second=0, microsecond=0)
    if end_hour < end:
        end_hour += timedelta(hours=1)
    while current <= end_hour:
        yield current
        current += timedelta(hours=1)


async def _download_hour_async(symbol: str, dt: datetime) -> Optional[pd.DataFrame]:
    """Async wrapper around synchronous _download_hour + _parse_bi5."""
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, _download_hour, symbol, dt)
    if not raw:
        return None
    df = await loop.run_in_executor(None, _parse_bi5, raw, symbol)
    if df.empty:
        return None
    # Convert time_ms offset to absolute UTC timestamp
    df["timestamp"] = dt.replace(tzinfo=timezone.utc) + pd.to_timedelta(df["time_ms"], unit="ms")
    return df


class IngestionService:
    """Bulk tick ingestion from Dukascopy with checkpoint/resume and gap detection."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or _DefaultAsyncSessionLocal

    async def ingest_symbol_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        source: str = "dukascopy",
    ) -> int:
        """
        Download raw ticks for a symbol+date range and bulk-insert into TimescaleDB.
        Returns number of ticks inserted.
        """
        logger.info("[ingestion] %s %s -> %s", symbol, start.isoformat(), end.isoformat())

        # Upsert ingestion_state row as RUNNING
        await self._set_state(symbol, source, status="running", last_ingested_at=datetime.now(timezone.utc))

        total_inserted = 0
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_DUKA)

        async def _fetch_and_insert(dt: datetime) -> int:
            async with semaphore:
                df = await _download_hour_async(symbol, dt)
                if df is None or df.empty:
                    return 0
                count = await self._bulk_insert_ticks(df, symbol, source)
                # Checkpoint after every hour
                await self._set_state(
                    symbol, source,
                    status="running",
                    last_ingested_at=datetime.now(timezone.utc),
                    last_ingested_hour=dt,
                )
                return count

        tasks = [_fetch_and_insert(dt) for dt in _hour_generator(start, end)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.error("[ingestion] hour failed for %s: %s", symbol, r)
            else:
                total_inserted += r

        status = "completed" if total_inserted > 0 else "partial"
        await self._set_state(
            symbol, source,
            status=status,
            last_ingested_at=datetime.now(timezone.utc),
            total_ticks=total_inserted,
        )
        logger.info("[ingestion] %s done — %d ticks inserted", symbol, total_inserted)
        return total_inserted

    async def detect_gaps(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        source: str = "dukascopy",
        max_gap_minutes: int = 5,
    ) -> List[Tuple[datetime, datetime]]:
        """
        Detect missing hours where we expected ticks but have none.
        Returns list of (gap_start, gap_end) tuples.
        """
        async with self.session_factory() as session:
            # Query all distinct hours we have ticks for
            result = await session.execute(
                text("""
                    SELECT DISTINCT date_trunc('hour', timestamp) AS hour
                    FROM ticks
                    WHERE symbol = :symbol AND source = :source
                      AND timestamp BETWEEN :start AND :end
                    ORDER BY hour
                """),
                {"symbol": symbol, "source": source, "start": start, "end": end},
            )
            present_hours = {row[0].replace(tzinfo=timezone.utc) if row[0].tzinfo is None else row[0] for row in result.fetchall()}

        gaps: List[Tuple[datetime, datetime]] = []
        expected = set(_hour_generator(start, end))
        missing = sorted(expected - present_hours)

        if not missing:
            return gaps

        # Coalesce contiguous missing hours into gap ranges
        gap_start = missing[0]
        gap_end = missing[0] + timedelta(hours=1)
        for h in missing[1:]:
            if h == gap_end:
                gap_end += timedelta(hours=1)
            else:
                gaps.append((gap_start, gap_end))
                gap_start = h
                gap_end = h + timedelta(hours=1)
        gaps.append((gap_start, gap_end))
        return gaps

    async def ingest_mt5_recent(
        self,
        symbol: str,
        lookback_hours: int = 72,
    ) -> int:
        """Fetch recent ticks from MT5 ZMQ and merge with Dukascopy data."""
        from app.services.data.mt5_zmq_client import MT5ZMQClient
        import time

        client = MT5ZMQClient()
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (lookback_hours * 3600 * 1000)

        try:
            ticks = await client.get_ticks(symbol, from_ms=start_ms, to_ms=end_ms)
        except Exception as exc:
            logger.warning("[mt5_fill] %s failed to fetch ticks: %s", symbol, exc)
            return 0
        finally:
            await client.close()

        if not ticks:
            return 0

        # Convert MT5 tick format to DataFrame
        df = pd.DataFrame(ticks)
        if df.empty:
            return 0
        df["timestamp"] = pd.to_datetime(df["time_ms"], unit="ms", utc=True)
        df["symbol"] = symbol
        df["source"] = "mt5_zmq"
        # MT5 copy_ticks returns: time, bid, ask, last, volume, flags
        # We map last->bid_vol (not ideal but we only have one volume field)
        # Actually, MT5 tick volume is usually total volume; set bid_vol=ask_vol=volume/2
        if "volume" in df.columns:
            df["bid_vol"] = df["volume"] / 2.0
            df["ask_vol"] = df["volume"] / 2.0
        else:
            df["bid_vol"] = 0.0
            df["ask_vol"] = 0.0

        # Deduplication: fetch existing Dukascopy timestamps for this range
        existing = await self._get_existing_timestamps(symbol, start_ms, end_ms)
        df = df[~df["timestamp"].isin(existing)]
        if df.empty:
            logger.info("[mt5_fill] %s: all ticks already present from Dukascopy", symbol)
            return 0

        count = await self._bulk_insert_ticks(df, symbol, "mt5_zmq")
        logger.info("[mt5_fill] %s: inserted %d new ticks", symbol, count)
        return count

    async def _get_existing_timestamps(self, symbol: str, start_ms: int, end_ms: int) -> set:
        """Return set of existing timestamps for deduplication."""
        async with self.session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT timestamp FROM ticks
                    WHERE symbol = :symbol
                      AND timestamp BETWEEN :start AND :end
                """),
                {
                    "symbol": symbol,
                    "start": datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc),
                    "end": datetime.fromtimestamp(end_ms / 1000.0, tz=timezone.utc),
                },
            )
            rows = result.fetchall()
        return {r[0] for r in rows}

    async def backfill_gaps(
        self,
        symbol: str,
        source: str = "dukascopy",
    ) -> int:
        """Detect gaps and re-ingest missing periods. Returns ticks inserted."""
        state = await self._get_state(symbol, source)
        if state is None or state.last_ingested_at is None:
            logger.warning("[backfill] No ingestion state for %s — cannot backfill", symbol)
            return 0

        # Look back 7 days from last ingestion
        end = state.last_ingested_at
        start = end - timedelta(days=7)
        gaps = await self.detect_gaps(symbol, start, end, source)
        total = 0
        for gap_start, gap_end in gaps:
            total += await self.ingest_symbol_range(symbol, gap_start, gap_end, source)
        return total

    async def get_pipeline_status(self) -> List[dict]:
        """Return ingestion state for all symbols."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).order_by(IngestionState.symbol)
            )
            rows = result.scalars().all()
        return [
            {
                "symbol": r.symbol,
                "source": r.source,
                "status": r.status,
                "last_ingested_at": r.last_ingested_at.isoformat() if r.last_ingested_at else None,
                "last_ingested_hour": r.last_ingested_hour.isoformat() if r.last_ingested_hour else None,
                "total_ticks": r.total_ticks,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _bulk_insert_ticks(
        self,
        df: pd.DataFrame,
        symbol: str,
        source: str,
    ) -> int:
        """Insert ticks via COPY for speed. Falls back to ORM bulk if COPY unavailable."""
        if df.empty:
            return 0
        # Ensure required columns exist
        df = df[["timestamp", "ask", "bid", "ask_vol", "bid_vol"]].copy()
        df["symbol"] = symbol
        df["source"] = source
        # Round timestamps to millisecond precision to avoid sub-ms noise
        df["timestamp"] = df["timestamp"].dt.floor("ms")

        # Use asyncpg COPY if available (Postgres), else ORM bulk insert
        from app.database import engine
        if "postgresql" in str(engine.url):
            return await self._copy_insert(df)
        else:
            return await self._orm_insert(df)

    async def _copy_insert(self, df: pd.DataFrame) -> int:
        """Use asyncpg COPY FROM for maximum throughput."""
        import asyncpg
        from app.database import engine
        url = str(engine.url)
        # Parse asyncpg DSN from SQLAlchemy URL
        # e.g. postgresql+asyncpg://user:pass@host/db -> postgresql://user:pass@host/db
        pg_url = url.replace("postgresql+asyncpg", "postgresql")
        conn = await asyncpg.connect(pg_url)
        try:
            records = [
                (
                    row["symbol"],
                    row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                    float(row["bid"]),
                    float(row["ask"]),
                    float(row["bid_vol"]) if pd.notna(row["bid_vol"]) else None,
                    float(row["ask_vol"]) if pd.notna(row["ask_vol"]) else None,
                    row["source"],
                )
                for _, row in df.iterrows()
            ]
            await conn.copy_records_to_table(
                "ticks",
                records=records,
                columns=["symbol", "timestamp", "bid", "ask", "bid_vol", "ask_vol", "source"],
            )
            return len(records)
        finally:
            await conn.close()

    async def _orm_insert(self, df: pd.DataFrame) -> int:
        """Fallback ORM bulk insert for SQLite/testing."""
        async with self.session_factory() as session:
            for _, row in df.iterrows():
                tick = Tick(
                    symbol=row["symbol"],
                    timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                    bid=float(row["bid"]),
                    ask=float(row["ask"]),
                    bid_vol=float(row["bid_vol"]) if pd.notna(row["bid_vol"]) else None,
                    ask_vol=float(row["ask_vol"]) if pd.notna(row["ask_vol"]) else None,
                    source=row["source"],
                    created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                )
                session.add(tick)
                await session.commit()
        return len(df)

    async def _set_state(
        self,
        symbol: str,
        source: str,
        status: str,
        last_ingested_at: Optional[datetime] = None,
        last_ingested_hour: Optional[datetime] = None,
        total_ticks: Optional[int] = None,
    ) -> None:
        """Upsert ingestion_state row."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.symbol == symbol,
                    IngestionState.source == source,
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = IngestionState(symbol=symbol, source=source, status=status)
                session.add(state)
            state.status = status
            if last_ingested_at is not None:
                state.last_ingested_at = last_ingested_at
            if last_ingested_hour is not None:
                state.last_ingested_hour = last_ingested_hour
            if total_ticks is not None:
                state.total_ticks = total_ticks
            await session.commit()

    async def _get_state(self, symbol: str, source: str) -> Optional[IngestionState]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.symbol == symbol,
                    IngestionState.source == source,
                )
            )
            return result.scalar_one_or_none()

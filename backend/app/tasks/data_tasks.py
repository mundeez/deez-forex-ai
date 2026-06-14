"""Celery tasks for historical tick data ingestion pipeline.

v0.8.0 M1 — Dukascopy primary source.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from app.services.data.ingestion_service import IngestionService, ACTIVE_SYMBOLS

logger = logging.getLogger("app.tasks.data")

# Default historical depth (env override)
HIST_START_DATE = os.environ.get("HIST_START_DATE", "")


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=240,
)
def ingest_dukascopy_daily(self, symbol: str = None):
    """
    Celery beat task: ingest previous day's ticks for all active symbols.
    Runs at 00:05 UTC daily.
    """
    service = IngestionService()
    symbols = [symbol] if symbol else ACTIVE_SYMBOLS

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)

    total = 0
    for sym in symbols:
        try:
            count = service.ingest_symbol_range(sym, start, end, source="dukascopy")
            total += count
        except Exception as exc:
            logger.error("[ingest_dukascopy_daily] %s failed: %s", sym, exc)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
    logger.info("[ingest_dukascopy_daily] total ticks: %d", total)
    return {"symbols": len(symbols), "ticks": total}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=480,
)
def ingest_historical_range(self, symbol: str, start_iso: str, end_iso: str):
    """
    Manual / on-demand ingestion for a specific symbol and date range.
    Called via FastAPI endpoint.
    """
    service = IngestionService()
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    try:
        count = service.ingest_symbol_range(symbol, start, end, source="dukascopy")
        return {"symbol": symbol, "ticks": count}
    except Exception as exc:
        logger.error("[ingest_historical_range] %s failed: %s", symbol, exc)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=240,
)
def detect_and_backfill_gaps(self, symbol: str = None):
    """
    Weekly gap detection + backfill.
    Runs Sunday 02:00 UTC.
    """
    service = IngestionService()
    symbols = [symbol] if symbol else ACTIVE_SYMBOLS
    total = 0
    for sym in symbols:
        try:
            count = service.backfill_gaps(sym, source="dukascopy")
            total += count
        except Exception as exc:
            logger.error("[detect_and_backfill_gaps] %s failed: %s", sym, exc)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
    logger.info("[detect_and_backfill_gaps] total backfilled: %d", total)
    return {"symbols": len(symbols), "ticks": total}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=120,
    soft_time_limit=90,
)
def ingest_mt5_fill(self, symbol: str = None):
    """
    Fill recent gaps from MT5 ZMQ (last 2h).
    Runs every 30 minutes for all active symbols.
    """
    service = IngestionService()
    symbols = [symbol] if symbol else ACTIVE_SYMBOLS
    total = 0
    for sym in symbols:
        try:
            count = service.ingest_mt5_recent(sym, lookback_hours=2)
            total += count
        except Exception as exc:
            logger.error("[ingest_mt5_fill] %s failed: %s", sym, exc)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
    logger.info("[ingest_mt5_fill] total filled: %d", total)
    return {"symbols": len(symbols), "ticks": total}

"""Celery tasks for historical tick data ingestion pipeline.

v0.8.0 M4 — Dukascopy primary source with state machine & dead-letter.
"""
import logging
import os
import asyncio
from datetime import datetime, timezone, timedelta

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from asgiref.sync import async_to_sync

from app.services.data.ingestion_service import IngestionService, ACTIVE_SYMBOLS
from app.services.data.pipeline_orchestrator import (
    PipelineOrchestrator, PipelineStatus, DeadLetterHandler,
)

logger = logging.getLogger("app.tasks.data")

# Default historical depth (env override)
HIST_START_DATE = os.environ.get("HIST_START_DATE", "")

orch = PipelineOrchestrator()
dl_handler = DeadLetterHandler()


def _sync_transition(*args, **kwargs):
    return async_to_sync(orch.transition)(*args, **kwargs)


def _sync_record_failure(*args, **kwargs):
    return async_to_sync(dl_handler.record_failure)(*args, **kwargs)


def _sync_kill_stale(*args, **kwargs):
    return async_to_sync(orch.kill_stale_jobs)(*args, **kwargs)


def _sync_retry_dl(*args, **kwargs):
    return async_to_sync(dl_handler.retry_dead_letter)(*args, **kwargs)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=240,
    queue="data_ingestion",
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
            _sync_transition(sym, "dukascopy", self.request.id,
                             None, PipelineStatus.RUNNING)
            count = service.ingest_symbol_range(sym, start, end, source="dukascopy")
            total += count
            _sync_transition(sym, "dukascopy", self.request.id,
                             PipelineStatus.RUNNING, PipelineStatus.COMPLETED,
                             metadata={"total_ticks": count})
        except Exception as exc:
            logger.error("[ingest_dukascopy_daily] %s failed: %s", sym, exc)
            _sync_transition(sym, "dukascopy", self.request.id,
                             PipelineStatus.RUNNING, PipelineStatus.RETRYING,
                             error=str(exc))
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            # Max retries exceeded -> dead letter
            _sync_record_failure(sym, "dukascopy", self.request.id,
                                 str(exc), payload={"start": start.isoformat(), "end": end.isoformat()})
            _sync_transition(sym, "dukascopy", self.request.id,
                             PipelineStatus.RETRYING, PipelineStatus.DEAD_LETTER,
                             error=str(exc))
    logger.info("[ingest_dukascopy_daily] total ticks: %d", total)
    return {"symbols": len(symbols), "ticks": total}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=480,
    queue="data_ingestion",
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
        _sync_transition(symbol, "dukascopy", self.request.id,
                         None, PipelineStatus.RUNNING)
        count = service.ingest_symbol_range(symbol, start, end, source="dukascopy")
        _sync_transition(symbol, "dukascopy", self.request.id,
                         PipelineStatus.RUNNING, PipelineStatus.COMPLETED,
                         metadata={"total_ticks": count})
        return {"symbol": symbol, "ticks": count}
    except Exception as exc:
        logger.error("[ingest_historical_range] %s failed: %s", symbol, exc)
        _sync_transition(symbol, "dukascopy", self.request.id,
                         PipelineStatus.RUNNING, PipelineStatus.RETRYING,
                         error=str(exc))
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        _sync_record_failure(symbol, "dukascopy", self.request.id,
                             str(exc), payload={"start": start_iso, "end": end_iso})
        _sync_transition(symbol, "dukascopy", self.request.id,
                         PipelineStatus.RETRYING, PipelineStatus.DEAD_LETTER,
                         error=str(exc))
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=240,
    queue="data_ingestion",
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
            _sync_transition(sym, "dukascopy", self.request.id,
                             None, PipelineStatus.RUNNING)
            count = service.backfill_gaps(sym, source="dukascopy")
            total += count
            _sync_transition(sym, "dukascopy", self.request.id,
                             PipelineStatus.RUNNING, PipelineStatus.COMPLETED,
                             metadata={"total_ticks": count})
        except Exception as exc:
            logger.error("[detect_and_backfill_gaps] %s failed: %s", sym, exc)
            _sync_transition(sym, "dukascopy", self.request.id,
                             PipelineStatus.RUNNING, PipelineStatus.RETRYING,
                             error=str(exc))
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            _sync_record_failure(sym, "dukascopy", self.request.id, str(exc))
            _sync_transition(sym, "dukascopy", self.request.id,
                             PipelineStatus.RETRYING, PipelineStatus.DEAD_LETTER,
                             error=str(exc))
    logger.info("[detect_and_backfill_gaps] total backfilled: %d", total)
    return {"symbols": len(symbols), "ticks": total}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=120,
    soft_time_limit=90,
    queue="data_ingestion",
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
            _sync_transition(sym, "mt5_zmq", self.request.id,
                             None, PipelineStatus.RUNNING)
            count = service.ingest_mt5_recent(sym, lookback_hours=2)
            total += count
            _sync_transition(sym, "mt5_zmq", self.request.id,
                             PipelineStatus.RUNNING, PipelineStatus.COMPLETED,
                             metadata={"total_ticks": count})
        except Exception as exc:
            logger.error("[ingest_mt5_fill] %s failed: %s", sym, exc)
            _sync_transition(sym, "mt5_zmq", self.request.id,
                             PipelineStatus.RUNNING, PipelineStatus.RETRYING,
                             error=str(exc))
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            _sync_record_failure(sym, "mt5_zmq", self.request.id, str(exc))
            _sync_transition(sym, "mt5_zmq", self.request.id,
                             PipelineStatus.RETRYING, PipelineStatus.DEAD_LETTER,
                             error=str(exc))
    logger.info("[ingest_mt5_fill] total filled: %d", total)
    return {"symbols": len(symbols), "ticks": total}


@shared_task(
    bind=True,
    time_limit=60,
    soft_time_limit=30,
)
def kill_stale_jobs(self, stale_minutes: int = 30):
    """
    Monitor task: mark ingestion jobs stuck in RUNNING for too long as FAILED.
    Runs every 10 minutes via Celery beat.
    """
    count = _sync_kill_stale(stale_minutes=stale_minutes)
    return {"killed": count}


@shared_task(
    bind=True,
    time_limit=120,
    soft_time_limit=90,
    queue="dead_letter",
)
def retry_dead_letter_job(self, symbol: str, source: str):
    """
    Manually retry a dead-letter job by re-queuing the appropriate task.
    """
    success = _sync_retry_dl(symbol, source)
    if not success:
        return {"error": f"No dead-letter job found for {symbol}/{source}"}

    # Re-queue the appropriate task based on source
    if source == "dukascopy":
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=1)
        ingest_historical_range.delay(symbol=symbol, start_iso=start.isoformat(), end_iso=end.isoformat())
    elif source == "mt5_zmq":
        ingest_mt5_fill.delay(symbol=symbol)

    return {"symbol": symbol, "source": source, "status": "requeued"}


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=120,
    soft_time_limit=90,
    queue="data_ingestion",
)
def ingest_fred_macro(self, lookback_days: int = 365):
    """Daily FRED macro data ingestion.  Runs at 06:00 UTC."""
    import asyncio
    from app.services.data.fred_client import FREDClient
    from app.database import get_celery_session
    async def _run():
        async with get_celery_session()() as db:
            client = FREDClient()
            return await client.ingest_all(db, lookback_days=lookback_days)
    return asyncio.run(_run())


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=600,
    time_limit=300,
    soft_time_limit=240,
    queue="data_ingestion",
)
def ingest_cot_weekly(self):
    """Weekly CFTC COT report ingestion.  Runs Monday 10:00 UTC."""
    import asyncio
    from app.services.data.cot_client import COTClient
    from app.database import get_celery_session
    async def _run():
        async with get_celery_session()() as db:
            client = COTClient()
            return await client.ingest(db)
    return asyncio.run(_run())


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=120,
    soft_time_limit=90,
    queue="data_ingestion",
)
def ingest_yfinance_macro(self, period: str = "1mo"):
    """Daily yfinance macro data ingestion (DXY, VIX, yields, indices).  Runs at 07:00 UTC."""
    import asyncio
    from app.services.data.macro_client import MacroClient
    from app.database import get_celery_session
    async def _run():
        async with get_celery_session()() as db:
            client = MacroClient()
            return await client.ingest_all(db, period=period)
    return asyncio.run(_run())


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    time_limit=120,
    soft_time_limit=90,
    queue="data_ingestion",
)
def backfill_dukascopy_5y(self, symbol: str = None):
    """Trigger 5-year Dukascopy backfill for all active symbols (or one symbol).
    Queues individual ingest_historical_range tasks per symbol.
    """
    from app.services.data.ingestion_service import ACTIVE_SYMBOLS
    from datetime import datetime, timezone, timedelta

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * 5)
    symbols = [symbol] if symbol else ACTIVE_SYMBOLS

    queued = 0
    for sym in symbols:
        try:
            ingest_historical_range.delay(
                symbol=sym,
                start_iso=start.isoformat(),
                end_iso=end.isoformat(),
            )
            queued += 1
            logger.info("Queued 5y backfill for %s (%s -> %s)", sym, start.date(), end.date())
        except Exception as exc:
            logger.error("Failed to queue 5y backfill for %s: %s", sym, exc)
    return {"symbols": queued, "start": start.isoformat(), "end": end.isoformat()}

"""Pipeline orchestration: state machine, dead-letter, rate limiting.

v0.8.0 M4
"""
import logging
import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List

from sqlalchemy import text, select, desc
from app.database import AsyncSessionLocal
from app.models import IngestionState

logger = logging.getLogger("app.services.data.pipeline")


class PipelineStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class PipelineOrchestrator:
    """Track and manage ingestion jobs through a state machine."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or AsyncSessionLocal

    async def transition(
        self,
        symbol: str,
        source: str,
        task_id: str,
        from_status: Optional[PipelineStatus],
        to_status: PipelineStatus,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Atomically transition a job from one state to another."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.symbol == symbol,
                    IngestionState.source == source,
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = IngestionState(
                    symbol=symbol,
                    source=source,
                    status=to_status.value,
                )
                session.add(state)

            # Validate transition
            if from_status and state.status != from_status.value:
                logger.warning(
                    "[pipeline] Invalid transition for %s/%s: expected %s, got %s",
                    symbol, source, from_status.value, state.status,
                )

            state.status = to_status.value
            state.last_ingested_at = datetime.now(timezone.utc)
            if metadata:
                # Store metadata in a JSON-friendly way via existing columns
                if "total_ticks" in metadata:
                    state.total_ticks = metadata["total_ticks"]
                if "last_ingested_hour" in metadata:
                    state.last_ingested_hour = metadata["last_ingested_hour"]
            if error:
                # Error stored in notes column if available, else log only
                logger.error("[pipeline] %s/%s error: %s", symbol, source, error)

            await session.commit()
            logger.info(
                "[pipeline] %s/%s: %s -> %s",
                symbol, source,
                from_status.value if from_status else "None",
                to_status.value,
            )

    async def get_job(self, symbol: str, source: str) -> Optional[Dict[str, Any]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.symbol == symbol,
                    IngestionState.source == source,
                )
            )
            state = result.scalar_one_or_none()
        if state is None:
            return None
        return {
            "symbol": state.symbol,
            "source": state.source,
            "status": state.status,
            "last_ingested_at": state.last_ingested_at.isoformat() if state.last_ingested_at else None,
            "last_ingested_hour": state.last_ingested_hour.isoformat() if state.last_ingested_hour else None,
            "total_ticks": state.total_ticks,
        }

    async def list_jobs(
        self,
        status: Optional[PipelineStatus] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        async with self.session_factory() as session:
            query = select(IngestionState).order_by(desc(IngestionState.last_ingested_at))
            if status:
                query = query.where(IngestionState.status == status.value)
            if source:
                query = query.where(IngestionState.source == source)
            result = await session.execute(query.limit(limit))
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

    async def kill_stale_jobs(self, stale_minutes: int = 30) -> int:
        """Mark jobs that have been RUNNING for too long as FAILED."""
        cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(minutes=stale_minutes)
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.status == PipelineStatus.RUNNING.value,
                    IngestionState.last_ingested_at < cutoff,
                )
            )
            stale = result.scalars().all()
            count = 0
            for job in stale:
                job.status = PipelineStatus.FAILED.value
                count += 1
            await session.commit()
        logger.info("[pipeline] Killed %d stale jobs", count)
        return count


# ------------------------------------------------------------------
# Simple in-memory rate limiter for Dukascopy (per-symbol)
# ------------------------------------------------------------------

class _TokenBucket:
    """Thread-safe token bucket for async rate limiting."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max tokens
        self.tokens = capacity
        self.last_update = datetime.now(timezone.utc)
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> bool:
        async with self._lock:
            now = datetime.now(timezone.utc)
            elapsed = (now - self.last_update).total_seconds()
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def wait(self, tokens: float = 1.0):
        while not await self.acquire(tokens):
            deficit = tokens - self.tokens
            wait_time = deficit / self.rate
            await asyncio.sleep(wait_time)


# Per-symbol Dukascopy rate limiters: 4 concurrent downloads max,
# with a global 10 req/sec burst limit per symbol.
_DUKA_BUCKETS: Dict[str, _TokenBucket] = {}
_DUKA_GLOBAL = _TokenBucket(rate=10.0, capacity=20.0)


async def duka_rate_limit(symbol: str):
    """Wait until both per-symbol and global Dukascopy rate limits allow."""
    bucket = _DUKA_BUCKETS.setdefault(symbol, _TokenBucket(rate=2.0, capacity=4.0))
    await bucket.wait(1.0)
    await _DUKA_GLOBAL.wait(1.0)


class DeadLetterHandler:
    """Handle tasks that have exceeded max retries."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or AsyncSessionLocal

    async def record_failure(
        self,
        symbol: str,
        source: str,
        task_id: str,
        error: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.symbol == symbol,
                    IngestionState.source == source,
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = IngestionState(symbol=symbol, source=source)
                session.add(state)
            state.status = PipelineStatus.DEAD_LETTER.value
            state.last_ingested_at = datetime.now(timezone.utc)
            await session.commit()
        logger.error(
            "[dead_letter] %s/%s task=%s error=%s payload=%s",
            symbol, source, task_id, error, payload,
        )

    async def list_dead_letter(
        self,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return await PipelineOrchestrator(session_factory=self.session_factory).list_jobs(
            status=PipelineStatus.DEAD_LETTER, limit=limit,
        )

    async def retry_dead_letter(self, symbol: str, source: str) -> bool:
        """Manually retry a dead-letter job by resetting its status to queued."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(IngestionState).where(
                    IngestionState.symbol == symbol,
                    IngestionState.source == source,
                    IngestionState.status == PipelineStatus.DEAD_LETTER.value,
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                return False
            state.status = PipelineStatus.QUEUED.value
            state.last_ingested_at = datetime.now(timezone.utc)
            await session.commit()
        logger.info("[dead_letter] Retrying %s/%s", symbol, source)
        return True

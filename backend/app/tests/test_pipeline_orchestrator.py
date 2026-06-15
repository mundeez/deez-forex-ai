"""Tests for pipeline orchestration (v0.8.0 M4)."""
import pytest
from datetime import datetime, timezone

from app.tests.conftest import AsyncSessionLocal
from app.services.data.pipeline_orchestrator import (
    PipelineOrchestrator, PipelineStatus, DeadLetterHandler,
)


@pytest.mark.asyncio
async def test_pipeline_transition(db_engine):
    """PipelineOrchestrator should track state transitions."""
    orch = PipelineOrchestrator(session_factory=AsyncSessionLocal)
    await orch.transition("EURUSD", "dukascopy", "task-123",
                           None, PipelineStatus.RUNNING)
    job = await orch.get_job("EURUSD", "dukascopy")
    assert job is not None
    assert job["status"] == "running"
    assert job["symbol"] == "EURUSD"

    await orch.transition("EURUSD", "dukascopy", "task-123",
                           PipelineStatus.RUNNING, PipelineStatus.COMPLETED,
                           metadata={"total_ticks": 1000})
    job = await orch.get_job("EURUSD", "dukascopy")
    assert job["status"] == "completed"
    assert job["total_ticks"] == 1000


@pytest.mark.asyncio
async def test_pipeline_list_jobs(db_engine):
    """PipelineOrchestrator should list jobs by status."""
    orch = PipelineOrchestrator(session_factory=AsyncSessionLocal)
    await orch.transition("EURUSD", "dukascopy", "t1", None, PipelineStatus.FAILED)
    await orch.transition("GBPUSD", "dukascopy", "t2", None, PipelineStatus.FAILED)
    await orch.transition("USDJPY", "mt5_zmq", "t3", None, PipelineStatus.COMPLETED)

    failed = await orch.list_jobs(status=PipelineStatus.FAILED)
    assert len(failed) == 2

    completed = await orch.list_jobs(status=PipelineStatus.COMPLETED)
    assert len(completed) == 1
    assert completed[0]["symbol"] == "USDJPY"


@pytest.mark.asyncio
async def test_dead_letter_handler(db_engine):
    """DeadLetterHandler should record and list failures."""
    dl = DeadLetterHandler(session_factory=AsyncSessionLocal)
    await dl.record_failure("XAUUSD", "dukascopy", "task-999",
                             "network timeout", payload={"start": "2024-01-01"})

    jobs = await dl.list_dead_letter()
    assert len(jobs) >= 1
    assert any(j["symbol"] == "XAUUSD" and j["status"] == "dead_letter" for j in jobs)


@pytest.mark.asyncio
async def test_retry_dead_letter(db_engine):
    """DeadLetterHandler should allow retrying dead-letter jobs."""
    dl = DeadLetterHandler(session_factory=AsyncSessionLocal)
    orch = PipelineOrchestrator(session_factory=AsyncSessionLocal)
    await orch.transition("AUDUSD", "dukascopy", "t4", None, PipelineStatus.DEAD_LETTER)

    success = await dl.retry_dead_letter("AUDUSD", "dukascopy")
    assert success is True

    job = await orch.get_job("AUDUSD", "dukascopy")
    assert job["status"] == "queued"

    # Non-existent job should return False
    success = await dl.retry_dead_letter("NOTREAL", "dukascopy")
    assert success is False


@pytest.mark.asyncio
async def test_kill_stale_jobs(db_engine):
    """PipelineOrchestrator should mark old RUNNING jobs as FAILED."""
    orch = PipelineOrchestrator(session_factory=AsyncSessionLocal)
    # Create a running job via transition, then update timestamp to stale via raw SQL
    await orch.transition("EURGBP", "dukascopy", "t5", None, PipelineStatus.RUNNING)

    # Update timestamp to 2 hours ago using the shared engine
    from sqlalchemy import text
    import datetime as dt
    stale_time = dt.datetime.now(timezone.utc) - dt.timedelta(hours=2)
    async with db_engine.begin() as conn:
        await conn.execute(
            text("UPDATE ingestion_state SET last_ingested_at = :ts WHERE symbol = :sym AND source = :src"),
            {"ts": stale_time, "sym": "EURGBP", "src": "dukascopy"}
        )

    count = await orch.kill_stale_jobs(stale_minutes=30)
    assert count == 1

    job = await orch.get_job("EURGBP", "dukascopy")
    assert job["status"] == "failed"

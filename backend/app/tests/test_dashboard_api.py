"""Tests for dashboard API endpoints (v0.8.0 M5).

These endpoints use PipelineOrchestrator with AsyncSessionLocal.
On SQLite in-memory, cross-connection table visibility is unreliable,
so we skip these when not running against PostgreSQL.
"""
import os
import pytest

import pytest

skip_sqlite = pytest.mark.skipif(
    os.environ.get("DATABASE_URL", "").startswith("sqlite"),
    reason="Pipeline endpoints require PostgreSQL for session consistency"
)


@skip_sqlite
@pytest.mark.asyncio
async def test_pipeline_summary_endpoint(async_client):
    """Pipeline summary endpoint should return status breakdown."""
    response = await async_client.get("/api/v1/data/pipeline/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_jobs" in data
    assert "status_breakdown" in data


@skip_sqlite
@pytest.mark.asyncio
async def test_pipeline_jobs_endpoint(async_client):
    """Pipeline jobs endpoint should return list of jobs."""
    response = await async_client.get("/api/v1/data/pipeline/jobs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@skip_sqlite
@pytest.mark.asyncio
async def test_dead_letter_endpoint(async_client):
    """Dead letter endpoint should return list (possibly empty)."""
    response = await async_client.get("/api/v1/data/pipeline/dead-letter")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@skip_sqlite
@pytest.mark.asyncio
async def test_kill_stale_endpoint(async_client):
    """Kill stale endpoint should queue a task."""
    response = await async_client.post("/api/v1/data/pipeline/kill-stale")
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data

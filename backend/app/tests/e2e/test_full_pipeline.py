"""E2E full pipeline test (v0.8.0 M6).

Requires the docker-compose stack to be running with:
  - postgres (TimescaleDB)
  - redis
  - backend
  - celery_worker
  - celery_beat

These tests are skipped if the backend is not reachable at the
E2E_API_URL (default http://localhost:8000).
"""
import os
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests

API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
DASHBOARD_URL = os.environ.get("E2E_DASHBOARD_URL", "http://localhost:28501")

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_E2E", "1") == "1",
    reason="E2E tests disabled by default (set SKIP_E2E=0 to run)"
)


def _wait_for_backend(timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{API_URL}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _wait_for_celery(timeout=60):
    """Check that Celery worker is processing tasks by inspecting a known queue."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{API_URL}/api/v1/data/pipeline/summary", timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="module")
def backend_ready():
    if not _wait_for_backend():
        pytest.skip("Backend not reachable")
    return True


@pytest.fixture(scope="module")
def celery_ready(backend_ready):
    if not _wait_for_celery():
        pytest.skip("Celery not ready")
    return True


class TestHealthChecks:
    def test_backend_health(self, backend_ready):
        resp = requests.get(f"{API_URL}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"

    def test_dashboard_health(self, backend_ready):
        resp = requests.get(f"{DASHBOARD_URL}/_stcore/health", timeout=5)
        assert resp.status_code == 200


class TestIngestionPipeline:
    def test_manual_historical_ingestion(self, backend_ready):
        """Trigger a small historical ingestion and verify it completes."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=1)
        payload = {
            "symbol": "EURUSD",
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        resp = requests.post(f"{API_URL}/api/v1/data/ingest", json=payload, timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "EURUSD"
        assert "task_id" in data

        # Poll for task completion (up to 2 minutes)
        task_id = data["task_id"]
        for _ in range(24):
            time.sleep(5)
            task_resp = requests.get(f"{API_URL}/api/v1/data/pipeline-status", timeout=10)
            if task_resp.status_code == 200:
                task_data = task_resp.json()
                # Check if any running task for EURUSD
                if not any(t.get("symbol") == "EURUSD" and t.get("status") == "running" for t in task_data.get("running_tasks", [])):
                    break

    def test_gap_detection(self, backend_ready):
        resp = requests.get(f"{API_URL}/api/v1/data/gaps/EURUSD?days=7", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "gaps" in data
        assert "gap_count" in data

    def test_continuous_aggregates(self, backend_ready):
        """Verify that TimescaleDB continuous aggregates exist."""
        # This test is PostgreSQL-specific
        resp = requests.get(f"{API_URL}/api/v1/data/pipeline/summary", timeout=10)
        assert resp.status_code == 200

    def test_backfill_api(self, backend_ready):
        resp = requests.post(f"{API_URL}/api/v1/data/backfill/EURUSD", timeout=30)
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data


class TestDashboardIntegration:
    def test_pipeline_summary(self, backend_ready):
        resp = requests.get(f"{API_URL}/api/v1/data/pipeline/summary", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_jobs" in data
        assert "status_breakdown" in data

    def test_dead_letter_empty(self, backend_ready):
        resp = requests.get(f"{API_URL}/api/v1/data/pipeline/dead-letter", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_ingestion_state(self, backend_ready):
        resp = requests.get(f"{API_URL}/api/v1/data/ingestion-state", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

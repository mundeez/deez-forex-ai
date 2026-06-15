#!/usr/bin/env bash
# Automated release script for deez-forex-ai v0.8.0
# Usage: ./scripts/release.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VERSION="v0.8.0"
PREVIOUS_TAG="v0.7.0"

echo "============================================"
echo "  Deez Forex AI Release Script"
echo "  Target version: $VERSION"
echo "============================================"

# 1. Verify git is clean
echo "[1/6] Checking working tree..."
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: Working tree is not clean. Commit or stash changes first."
    git status --short
    exit 1
fi

# 2. Run test suite
echo "[2/6] Running backend test suite..."
cd backend
source .test-venv/bin/activate || true
python -m pytest app/tests/ -q --tb=short || {
    echo "ERROR: Tests failed. Fix before releasing."
    exit 1
}
cd ..

# 3. Verify docker-compose builds
echo "[3/6] Verifying Docker compose build..."
docker compose build --no-cache backend celery_worker celery_beat dashboard || {
    echo "ERROR: Docker build failed."
    exit 1
}

# 4. Tag release
echo "[4/6] Tagging release $VERSION..."
if git rev-parse "$VERSION" >/dev/null 2>&1; then
    echo "Tag $VERSION already exists. Deleting old tag..."
    git tag -d "$VERSION" || true
fi
git tag -a "$VERSION" -m "Release $VERSION

Full tick data pipeline with TimescaleDB:
- M0: TimescaleDB migration, hypertables, compression
- M1: Dukascopy bulk historical ingestion
- M2: MT5 ZMQ live tick fill-in & spread capture
- M3: TimescaleDB continuous aggregates for bar generation
- M4: Pipeline orchestration (state machine, dead-letter, rate limiting)
- M5: Streamlit pipeline dashboard with 6 pages
- M6: E2E pytest-docker suite & automated release"

# 5. Generate release notes
echo "[5/6] Generating release notes..."
cat > /tmp/release_notes.md << 'RELNOTES'
## What's New in v0.8.0

### Data Pipeline Infrastructure
- **TimescaleDB Migration**: Full migration to TimescaleDB with hypertables for ticks, bars, and ingestion_state. Compression policies enabled.
- **Dukascopy Ingestion Engine**: Async bulk download with checkpoint/resume, concurrent semaphore (max 4), bulk COPY insert, and gap detection.
- **MT5 ZMQ Live Fill-in**: Real-time tick capture from MT5 via ZMQ, merged with Dukascopy data for spread capture.
- **Continuous Aggregates**: Auto-generated 1m/5m/15m/1h/4h/1d/1w bars from raw ticks with refresh policies and graduated retention.
- **Pipeline Orchestration**: State machine tracking, dead-letter queue for failed tasks, per-symbol rate limiting, and dedicated Celery queues.
- **Streamlit Dashboard**: 6-page monitoring dashboard (Overview, Jobs, Dead Letter, Gap Analysis, Data Quality, System Health).

### API Endpoints
- `POST /api/v1/data/ingest` — manual historical ingestion
- `GET/POST /api/v1/data/pipeline/*` — pipeline orchestration
- `GET /api/v1/data/gaps/{symbol}` — gap detection
- `POST /api/v1/data/backfill/{symbol}` — trigger backfill
- `GET /api/v1/data/ingestion-state` — ingestion status

### Operations
- Docker Compose stack with healthchecks
- Celery Beat schedule: daily ingestion at 00:05 UTC, gap detection Sundays, MT5 fill every 30min
- E2E test suite with pytest-docker
RELNOTES

echo "Release notes written to /tmp/release_notes.md"

# 6. Summary
echo "[6/6] Release preparation complete!"
echo ""
echo "Next steps:"
echo "  1. Review the tag: git show $VERSION"
echo "  2. Push the tag: git push origin $VERSION"
echo "  3. Create GitHub release: gh release create $VERSION --title '$VERSION' --notes-file /tmp/release_notes.md"
echo ""
echo "Tags on this branch:"
git tag -l | sort -V | tail -10

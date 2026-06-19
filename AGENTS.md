
## Backtest Monitoring

Full expanding-window backtest (task ID: `8008953e-abd0-40c9-86f7-d2aecd75cfd3`)
- Date range: Oct 15, 2025 → Jun 19, 2026
- Symbols: 9 pairs
- Starting equity: $200
- Decision frequency: once per session (4x/day)

Monitor progress:
```bash
docker compose exec backend python -c "
from celery.result import AsyncResult
from app.celery_app import celery_app
r = AsyncResult('8008953e-abd0-40c9-86f7-d2aecd75cfd3', app=celery_app)
print('status:', r.status)
"

# Watch live logs
docker compose logs -f celery_worker 2>&1 | grep -E "backtest|Checkpoint|Month|equity"

# Check all checkpoints
docker compose logs celery_worker 2>&1 | grep Checkpoint
```

Expected runtime: 8–16 hours (free models with rate limiting).

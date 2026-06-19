
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

## Standalone Backtest (Active)

Run ID: `20260619_055828`

Status: **RUNNING** in backend container (NOT Celery)
- Progress: 5/988 sessions (Oct 16, 2025)
- Equity: $203.84 (up from $200)
- Trades: 4 (3 wins, 1 loss — $2.73 + $1.41 + $1.78 - $2.08)
- Max drawdown: 1.02%
- Errors: 0 (all API failures handled gracefully)

Monitor in real-time:
```bash
docker compose logs -f backend 2>&1 | grep -E "backtest_standalone|Checkpoint"
```

Check progress instantly:
```bash
docker compose exec backend cat /app/backtest_checkpoints/20260619_055828_state.json
```

View trades:
```bash
docker compose exec backend cat /app/backtest_checkpoints/20260619_055828_trades.jsonl
```

Resume if interrupted (automatic on restart):
```bash
docker compose exec backend python /app/run_backtest_standalone.py
```

# FX DEEZ — Improvement Plan & Architectural Audit

**Status:** Living document. Created 2026-05-26 from comprehensive technical audit.
**Audience:** Any engineer or AI agent picking up this work in a future session.
**Scope:** End-to-end improvement of the deez-forex-ai trading platform — exit optimization, missing quant metrics, trade visibility, drilldown analytics, and continuous AI learning.

> **How to use this document.** Sections 1–4 are the audit (read-only context). Section 5 is the phased roadmap. Section 6 is the active work item with concrete file changes and verification steps. Section 7 captures the user's product decisions you must respect. Section 8 tells you exactly how to resume.

---

## 0. Project Snapshot

| Fact | Value |
|---|---|
| Repo root | `/home/mundeez/CascadeProjects/windsurf-project/deez-forex-ai/` |
| Live URL | https://fx.deeztechnology.solutions/ |
| Backend port (host) | `28000` (container `8000`) |
| Frontend port (host) | `23000` (container `3000`) |
| Postgres port (host) | `25432` (container `5432`) — user `forex`, db `deez_forex`, password `changeme` |
| Redis port (host) | `26379` |
| Qdrant ports (host) | `26333` HTTP, `26334` gRPC |
| Latest tag | `v0.8.1` (account snapshot reset on equity_balance fix) |
| GitHub repo | https://github.com/mundeez/deez-forex-ai |

**Stack.** FastAPI + SQLAlchemy async (asyncpg) + Celery (worker + beat) + Postgres 15 + Redis 7 + Qdrant + OpenRouter (free models default) + MetaAPI + MT5 ZMQ. Frontend Next.js 14 App Router + MUI 5 + Tailwind + lightweight-charts 4.1.3 + Redux Toolkit + axios.

**Quick health checks.**
```bash
curl -s http://localhost:28000/health | jq
curl -s http://localhost:28000/api/v1/system/health | jq
curl -s https://fx.deeztechnology.solutions/health | jq
docker ps --filter name=deez-forex
docker exec deez-forex-postgres psql -U forex -d deez_forex -c "\dt"
```

---

## 1. Architecture Map

### 1.1 Backend (`backend/app/`)

```
app/
├── main.py                    # FastAPI app, 29 REST endpoints, 1 WebSocket
├── config.py                  # Settings class, env-var defaults
├── database.py                # async engine, session factory, get_celery_session
├── models.py                  # SQLAlchemy ORM (10 tables)
├── schemas.py                 # Pydantic request/response models
├── enums.py                   # TradeStatus, TradeDirection, TradeMode, DataProvider, StrategyMode
├── celery_app.py              # Celery + beat schedule (7 periodic tasks)
├── logging_config.py
├── ai/
│   └── openrouter_client.py   # OpenRouter REST, TradeDecision schema, fallbacks
├── analysis/
│   ├── aggregator.py          # gather_all() — orchestrates technical/fundamental/sentiment
│   ├── technical.py           # EMA/RSI/MACD/BB/ATR/ADX/VWAP per timeframe
│   ├── fundamental.py         # economic calendar + interest-rate spread
│   └── sentiment.py           # news + retail + institutional (mocked)
├── backtest/engine.py         # BacktestEngine — used only on demand, never auto-scheduled
├── middleware/{rate_limit,request_id}.py
├── services/
│   ├── settings_service.py    # DB-backed settings + 5-min cache, equity_balance reset behavior
│   ├── news_service.py        # NewsAPI integration, halt windows
│   ├── notification_service.py  # Discord/Slack/Pushover/webhook
│   ├── vector_store.py        # Qdrant client, 32-dim encoding, upsert/update_outcome/search_similar
│   ├── websocket_broadcaster.py # Redis pub/sub for real-time push
│   ├── data/{metaapi_client,mt5_zmq_client,mt5_zmq_subscriber}.py
│   ├── execution/executor.py  # ExecutionService — trade lifecycle (place/close/SL-TP/trail/partial)
│   └── risk/manager.py        # RiskManager — validate, drawdown reduce, correlation (NOT IMPL)
├── suggestion_engine/engine.py  # session-overlap + profitability scoring
└── tasks/
    ├── analysis_tasks.py       # run_full_analysis, auto_select_pairs, record_hourly_performance
    └── execution_tasks.py      # check_open_positions, close_eod, close_weekend, update_daily_pnl, compute_pair_performance
```

### 1.2 Frontend (`frontend/src/`)

```
src/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                # Dashboard (3-column grid)
│   ├── providers.tsx           # Redux + MUI + Sonner
│   ├── globals.css
│   └── settings/page.tsx
├── components/
│   ├── Header.tsx
│   ├── ChartPanel.tsx          # lightweight-charts candles + EMA + Bollinger
│   ├── MarketInfoBar.tsx       # bid/ask/spread/session indicators
│   ├── ProfitMetricsPanel.tsx  # equity, daily/realized/unrealized PnL, win rate, profit factor, MaxDD, Sharpe, Expectancy ⚠️ broken
│   ├── PositionsPanel.tsx      # open positions list (no open_time)
│   ├── TradeHistoryPanel.tsx   # closed trades (no close_time/duration/session)
│   ├── SuggestionsPanel.tsx    # best-now + hourly timeline (no rationale)
│   ├── AIDecisionPanel.tsx     # recent AI decisions
│   ├── AnalysisPanel.tsx       # tech/fundamental/sentiment tabs
│   ├── ManualTradePanel.tsx    # manual entry form
│   ├── PairSelector.tsx        # active pairs (max 3)
│   ├── ManualOverrideToggle.tsx
│   └── common/ErrorBoundary.tsx  # exists but never wrapped around panels
├── hooks/useWebSocket.ts       # WS subscribe to prices/trades/ai_decisions/settings
├── store/                      # Redux Toolkit — configured but UNUSED
├── theme/index.ts              # MUI dark theme
├── types/index.ts              # TS interfaces ⚠️ missing fields (expectancy, equity_history)
└── utils/
    ├── api.ts                  # axios apiClient with retry — UNUSED, every component uses raw fetch()
    └── toast.ts
```

### 1.3 Database (10 tables)

| Table | Rows (audit time) | Notes |
|---|---|---|
| `ai_decisions` | 2,646 | Fully populated |
| `trades` | 182 (179 CLOSED, 3 OPEN) | **`close_reason` NULL on every row**; `highest_price_seen` set on 22%, `lowest_price_seen` on 4% |
| `daily_pnl` | 116 | Only `symbol='PORTFOLIO'` populated; per-symbol unused |
| `pair_performance_by_hour` | 55 | Populated by Celery hourly |
| `settings` | 50 keys | DB-backed runtime config |
| `account_snapshots` | 22 | Wiped on `equity_balance` setting change → Sharpe/MaxDD always thin |
| `active_pairs` | 3 | EURUSD, GBPUSD, AUDUSD |
| `market_data` | **0** | OHLCV never persisted; every analysis hits MetaAPI live |
| `market_state_snapshots` | **0** | SQL twin of Qdrant points — never written |
| `backtest_runs` | **0** | Never auto-scheduled, but `/portfolio/summary` reads MaxDD/Sharpe from this table → always 0 |

**Empirical patterns from the 179 closed trades:**

| Holding bucket | Trades | Total PnL | WR |
|---|---:|---:|---:|
| 0–5 min | 133 | +$8,610 | 47.4% |
| 5–30 min | 1 | +$28 | 100% |
| 30 min–2 h | 8 | +$193 | 87.5% |
| 2–8 h | **32** | **+$766** | **87.5%** |
| 8–24 h | 4 | +$64 | 100% |
| > 1 day | 1 | -$0.84 | 0% |

| Session at open | Trades | Avg PnL | WR |
|---|---:|---:|---:|
| Asian (00–07 UTC) | 43 | $192.07 | 46.5% |
| London-NY overlap (12–17) | 78 | $5.56 | 57.7% |
| NY (17–22 UTC) | 58 | $16.66 | 65.5% |

Counter-intuitive insight: longer holds win more on average; the 0-5 min bucket has the lowest WR (likely noise-triggered SL hits). The user's "profit decay" symptom is *not* statistically dominated by overnight exposure — it's caused by mechanical-only exits with no AI re-evaluation, which is the central design gap.

---

## 2. Root Cause Analysis (every issue → file:line)

### 🔴 Bug #1 — Max Drawdown & Sharpe always render `0`
**File:** `backend/app/main.py:571-582`
```python
max_dd_result = await db.execute(
    select(func.coalesce(func.min(models.BacktestRun.max_drawdown_pct), 0)).where(...)
)
sharpe_result = await db.execute(
    select(func.coalesce(func.avg(models.BacktestRun.sharpe_ratio), 0)).where(...)
)
```
Reads from `backtest_runs` (0 rows) instead of computing from live trades. Fix: compute from realized-trade equity curve.

### 🔴 Bug #2 — `close_reason` NULL on every closed trade
**Files:** `backend/app/services/execution/executor.py:129-165` + `backend/app/models.py:22-52`
```python
async def close_trade(..., close_reason: str = "sl_tp"):
    trade.exit_price = exit_price
    trade.status = models.TradeStatus.CLOSED
    trade.close_time = datetime.utcnow()
    if trade.rationale:
        trade.rationale += f" | Close reason: {close_reason}"   # ← only suffixes text
    # ← MISSING: trade.close_reason = close_reason
```
**Plus** the `close_reason` column is in the DB (via `migrate_add_columns.sql`) but **not declared on the SQLAlchemy `Trade` model**. ORM ↔ DB drift. Same drift for `partial_tp_hit`, `partial_profit_pnl`, `max_risk_amount`.

### 🔴 Bug #3 — Price-path data missing on most trades
**File:** `backend/app/services/execution/executor.py:276-360`
`highest_price_seen`/`lowest_price_seen` are only updated inside `check_trailing_stops`, gated on `trailing_stop_distance` being non-null. For trades without trailing distance, the price path is never recorded. Result: 78% of closed trades have NULL `highest_price_seen`. Without this we cannot compute MFE/MAE, the foundation of exit-timing learning.

### 🔴 Bug #4 — No AI re-evaluation of open positions
**File:** `backend/app/tasks/analysis_tasks.py` (entire file)
`run_full_analysis` only generates entry decisions for active pairs. There is no Celery task or service that asks "should we close trade X now?" Once opened, only mechanical SL/TP/trailing/max-duration/EOD close trades. This is the primary cause of the user's "profits later decrease because trades are closed too late" symptom.

### 🔴 Bug #5 — Qdrant `search_similar` is never called
**File:** `backend/app/services/vector_store.py:66` (function definition)
Grep across `backend/` shows zero call sites. The vector store is written to on every AI decision but never queried, so the AI never benefits from past similar setups. The `MarketStateSnapshot` SQL table that should mirror Qdrant points has 0 rows.

### 🔴 Bug #6 — Frontend renders `-` despite valid backend values
**File:** `frontend/src/components/ProfitMetricsPanel.tsx:107-133`
```jsx
<p>{stats?.win_rate ? `${stats.win_rate}%` : "-"}</p>          // ← falsy on 0
<p>{stats?.expectancy?.toFixed(2) || "-"}</p>                  // ← field missing from TS type
```
- Falsy check fails for `0` (legitimate value).
- `expectancy` and `equity_history` are missing from `PortfolioSummary` interface in `frontend/src/types/index.ts:49-61`.
- Backend correctly returns `expectancy: 53.96`, but TS type narrows it to `undefined`, optional chain fails, render is `-`.

### 🟠 Bug #7 — Trade visibility gaps
- `PositionsPanel.tsx:117-194`: `open_time` field exists but never rendered.
- `TradeHistoryPanel.tsx:49-68`: `close_time`, duration, session, entry/exit prices all unrendered.
- No drilldown route exists; clicking a trade does nothing.

### 🟠 Bug #8 — AI Suggestions opaque
`SuggestionsPanel.tsx:110-130` shows only score + recommendation + win_rate_24h; no rationale, no indicator weights, no similar past setups, no scenarios, no invalidation conditions, no expected holding.

### 🟡 Bug #9 — Account snapshots data-thin
**File:** `backend/app/services/settings_service.py:125-127`
Snapshots are wiped via `delete()` whenever `equity_balance` changes (the v0.8.1 fix). No periodic task rebuilds the curve. Sharpe/MaxDD computed from this would always be unreliable until ≥ N hours after every settings change.

### 🟡 Bug #10 — Strategy-mode mismatch on currently open trades
Current `strategy_mode = day_trading` enforces 120-min max duration (`executor.py:236`), yet 3 open trades are 624–695 min old. Either trades were opened under a different `strategy_mode`, or `check_and_close_time_based_positions` isn't running for them. Worth investigating during Round 1.

### 🟡 Other smells
- `correlation_guard_enabled` setting read but **no implementation** in `RiskManager`.
- `_fallback_decision` uses `random.choice(["BUY","SELL","HOLD"])` on neutral signal → non-deterministic.
- Missing indexes on `trades(status, symbol, close_time)`, `ai_decisions(timestamp)`.
- Settings cache TTL 5 min → settings changes take up to 5 min to take effect.
- Frontend Redux + axios `apiClient` configured but unused (dead code).
- ErrorBoundary defined but not wrapped around any panel.
- `/trades/stats` getting 429 rate-limited on the live page (UI over-polling at 15 s).

---

## 3. Architecture Recommendations

### 3.1 AI learning architecture — Hybrid Rule Engine + RAG (Qdrant) + outcome-aware learning

**Why this approach over alternatives:**
- ❌ **Pure RL** needs 10⁴–10⁵ episodes to converge safely; only 179 trades exist → catastrophic policy collapse risk.
- ❌ **Pure supervised ML** can't react to novel regimes (NFP days, central bank surprises).
- ❌ **Fine-tuning the LLM** unavailable on OpenRouter's free tier; even paid tiers risk overfit on 179 samples.
- ✅ **RAG via Qdrant** retrieves recent similar states naturally (regime-adaptive); inject summary into LLM prompt — same outcome, no training pipeline.
- ✅ **Rule-first fast path** catches obvious profit-lock-in / overnight cuts in milliseconds without LLM round-trip; LLM only consulted on ambiguous cases.
- ✅ **Capital preservation** is structurally enforced (rules first, AI as advisory).

**Three loops:**

```
LOOP 1 — ENTRY (existing, augmented)
  Analysis → Qdrant.search_similar(top_k=10, last_90d) →
  "Similar setups: 8W/2L, $128 avg, 80% WR, median 47 min, exits at 1.8R via trail" →
  inject into AI prompt → decision (entry, SL, TP, expected_holding_min, invalidation)

LOOP 2 — EXIT (NEW)  every 1–3 min for open trades
  Update price-path → MFE/MAE/peak_pnl → profit_decay_score
  Rule fast-path (auto-execute):
    - mfe ≥ 1R AND pullback > 50% of mfe              → close (profit lock)
    - holding > expected_holding_min × 1.5 AND pnl≤0  → close (stale)
    - approaching news event window                   → close (event)
    - overnight cutoff hour reached                   → close (cutoff)
  AI slow path (every 5–10 min, alert-only initially):
    - call OpenRouter with current state + entry context
    - "Close now?" with confidence gate ≥ 0.6 → notify; auto-execute optional later
  Every decision logged to trade_decision_events (append-only audit)

LOOP 3 — LEARNING (offline + on every close)
  Trade closes → vs.update_outcome (existing) AND mirror to MarketStateSnapshot SQL
  Insert exit_quality_score = realized_pnl / max(peak_pnl, 1)
  Nightly Celery: compute_pattern_priors (per-pair × session × strategy)
  Nightly Celery: rolling_backtest_30d → populate backtest_runs for trend monitoring
  Drift detector: alert if recent 30-trade WR diverges > 20% from 90-day avg
```

### 3.2 Schema additions (additive, backwards-compatible)

| Table | Change | Purpose |
|---|---|---|
| `trades` | + `close_reason` (model only — already in DB), `mfe_pips`, `mae_pips`, `peak_pnl`, `peak_pnl_time`, `session_at_open`, `session_at_close`, `expected_holding_min`, `actual_holding_min`, `exit_quality_score`, `regime_at_open` (JSONB), `partial_tp_hit`, `partial_profit_pnl`, `max_risk_amount` | Foundation of exit learning + ORM-DB sync |
| `account_snapshots` | + `baseline_equity` column; remove `equity_balance` wipe; add periodic 5-min writer | Reliable equity curve for Sharpe/MaxDD |
| `market_state_snapshots` | start populating to mirror Qdrant points | Joinable cross-reference |
| `backtest_runs` | start populating via nightly task | Trend monitoring |
| `trade_decision_events` (NEW) | `(id, trade_id, ts, kind ENTRY/CHECK/CLOSE, source AI/RULE/MANUAL, snapshot JSONB, action, rationale, confidence)` | Append-only decision audit |

### 3.3 New / extended API endpoints

| Endpoint | Phase | Purpose |
|---|---|---|
| `GET /api/v1/analytics/equity-curve` | 1 | Sparkline + analytics page data |
| `GET /api/v1/analytics/portfolio` | 2 | Replaces `/portfolio/summary`; live Sharpe/Sortino/Calmar/MaxDD/expectancy |
| `GET /api/v1/analytics/holding-distribution` | 2 | Histogram with PnL & WR per bucket |
| `GET /api/v1/analytics/by-session` | 2 | Per-session PnL/WR/avg |
| `GET /api/v1/analytics/by-hour` | 2 | Hourly breakdown (extends `pair_performance_by_hour`) |
| `GET /api/v1/trades/{id}` | 2 | Trade detail: full timeline, MFE/MAE, decision events, similar setups |
| `GET /api/v1/trades` | 2 | Add `from`, `to`, `pair`, `session`, `outcome`, `min_pnl`, `max_pnl`, `min_confidence`, `sort`, `cursor` |
| `GET /api/v1/positions/{id}/exit-recommendation` | 3 | AI's current view on closing this position (UI badge) |
| `GET /api/v1/suggestions/{id}/explain` | 4 | RAG-grounded rationale, indicator weights, similar setups, scenarios, invalidation |

### 3.4 Frontend additions

| Route / Component | Phase | Purpose |
|---|---|---|
| `ProfitMetricsPanel` (fix) | 1 | Live MaxDD/Sharpe/Expectancy + sparkline |
| `PositionsPanel` (fix) | 1 | open_time + session badge |
| `TradeHistoryPanel` (fix) | 1 | close_time + duration + session + R-multiple + close_reason |
| `/trades` (NEW) | 2 | Filterable list, CSV export, drilldown links |
| `/trades/[id]` (NEW) | 2 | Detail page: chart with markers, MFE/MAE shading, decision timeline, similar setups, "would-have-been-optimal-exit" overlay |
| `/analytics` (NEW) | 2 | Interactive equity curve, drawdown series, session heatmap, holding histogram |
| AI Suggestions "Why" expandable | 5 | Indicator weights, fundamental, similar setups, scenarios, invalidation |
| ErrorBoundary wraps every panel | 1 | Resilience |
| MUI Skeleton loading states | 1 | UX polish |
| Mobile responsive grid | 5 | Phone usability |
| Timezone selector + global formatter | 2 | UTC / local / IANA via dayjs |

---

## 4. Decisions Captured (RESPECT THESE)

The user has explicitly chosen the following — do not re-litigate without asking:

| Decision | Choice |
|---|---|
| Exit autonomy | **Rules auto-execute, AI exit re-eval is alert-only initially** |
| UI scope | **Full institutional UX** (the maximum option) |
| Phase order | **Metrics fix only first**, then re-plan with live data |
| Open positions during refactor | **Don't touch existing open trades**; add `overnight_cutoff_utc` setting (default OFF) for future positions |

When (and only when) Round 1 is shipped and the user has observed live metrics, re-engage to plan Round 2. At that point, present the deferred phases (2–6) for prioritization.

---

## 5. Phased Roadmap (full, all phases)

### Phase 1 — Data Foundation & Quick Wins **(Round 1, current)**
**Goal:** Fix broken metrics + ORM/DB drift + price-path data so future phases stand on truth.

**Backend**
1. Extend `Trade` ORM model with: `close_reason`, `partial_tp_hit`, `partial_profit_pnl`, `max_risk_amount`, `mfe_pips`, `mae_pips`, `peak_pnl`, `peak_pnl_time`, `session_at_open`, `session_at_close`, `actual_holding_min`.
2. Fix `executor.close_trade()` to write `trade.close_reason = close_reason`, stamp `session_at_close`, compute `actual_holding_min`.
3. Helper `app/services/sessions.py` — `classify_session(dt_utc) -> "asian" | "tokyo" | "london" | "ny" | "overlap" | "sydney"`.
4. Extend `executor.execute_trade()` to stamp `session_at_open`.
5. Always-populate price-path: in `check_and_close_positions` AND `check_trailing_stops`, update `highest_price_seen`/`lowest_price_seen` for **every** open trade on every check (not gated on trailing distance). Compute `peak_pnl` and `peak_pnl_time` whenever current PnL > stored peak. Compute `mfe_pips` and `mae_pips` (signed pip differences).
6. Replace `portfolio_summary` metrics: build a closed-trade equity curve `[start_equity + cumsum(pnl)]`, derive `peak_equity`, `max_drawdown_pct`, per-trade returns for Sharpe (annualized 260) + Sortino. Always non-`None` when ≥ 1 trade exists.
7. New endpoint `GET /api/v1/analytics/equity-curve` returning ordered `[{timestamp, equity, realized_pnl, unrealized_pnl, drawdown_pct}, ...]`.
8. Settings: `overnight_cutoff_enabled` (bool, default `false`), `overnight_cutoff_utc` (string `"HH:MM"`, default `"22:00"`).
9. Wire `_trading_paused` to reject new entries past cutoff when enabled. New Celery task `close_overnight_cutoff` running every 5 min that closes open trades when cutoff reached and setting enabled. Existing 3 open trades unaffected unless user enables.
10. SQL migration `backend/migrate_round1.sql`: `ALTER TABLE trades ADD COLUMN IF NOT EXISTS …` for the 11 new columns; `CREATE INDEX IF NOT EXISTS ix_trades_status_close_time ON trades(status, close_time DESC)`, `ix_trades_symbol`, `ix_ai_decisions_timestamp`. Run on container start (idempotent).
11. Tests `backend/app/tests/test_analytics.py` — synthetic trades (zero, all-win, all-loss, mixed), assert MaxDD/Sharpe/expectancy match closed-form values.

**Frontend**
1. `types/index.ts`: add `expectancy: number | null` and `equity_history?: {timestamp, equity}[]` to `PortfolioSummary`. Align `Trade` with backend (add `close_reason`, `mfe_pips`, `mae_pips`, `peak_pnl`, `session_at_open`, `session_at_close`, `actual_holding_min`).
2. `ProfitMetricsPanel.tsx`: replace falsy `{x ? : "-"}` pattern with `Number.isFinite(x) ? format(x) : "-"`. Render real sparkline from `equity_history` (drop the `equity_history` || [] line in the existing code).
3. `PositionsPanel.tsx`: render `open_time` formatted via `dayjs` and a session badge via small helper.
4. `TradeHistoryPanel.tsx`: render `close_time`, duration (`actual_holding_min`), session chip, entry → exit prices, R-multiple `(pnl_pct / |entry-SL|*entry)`, `close_reason` chip with color coding.
5. Reduce `/trades/stats` polling 15→30 s. The WS already pushes settings/trade events, so 30 s is plenty.
6. Wire `src/utils/api.ts` apiClient (already configured with retry+backoff) into the metrics + positions + history fetches.
7. Helper `src/utils/sessions.ts` mirroring backend classifier so UI can render sessions even on older trades that lack `session_at_open`.

**Verification**
- `curl http://localhost:28000/api/v1/portfolio/summary | jq '{max_drawdown_pct, sharpe_ratio, expectancy}'` returns non-zero values.
- Place a paper trade and let it close: `docker exec deez-forex-postgres psql -U forex -d deez_forex -c "SELECT id, close_reason, mfe_pips, peak_pnl, session_at_open FROM trades ORDER BY id DESC LIMIT 1;"` — all populated.
- `pytest backend/app/tests/test_analytics.py -v` green.
- Browser at `https://fx.deeztechnology.solutions/`: Max Drawdown / Sharpe / Expectancy show numbers; sparkline renders; Open Positions show open time + session; Trade History shows close time + duration + session + close reason. No 429 errors in DevTools network.
- DB: `SELECT COUNT(*) FILTER (WHERE highest_price_seen IS NOT NULL)::float / COUNT(*) FROM trades WHERE status='CLOSED' AND close_time > now() - interval '1 day'` ≥ 0.95.

**Rollback**
- All schema changes additive (`IF NOT EXISTS`), redeploy old code is safe.
- `overnight_cutoff_enabled` default `false` — no behavioral change unless user opts in.
- Old metric path can stay behind a `use_live_metrics` setting if needed (probably unnecessary).

---

### Phase 2 — Trade Visibility & Drilldown
**Goal:** Make the data the platform produces actually navigable.

1. Backend: extend `GET /api/v1/trades` with filters (`from`, `to`, `pair`, `session`, `outcome`, `min_pnl`, `max_pnl`, `min_confidence`), sorting (`sort_by`, `sort_dir`), and cursor pagination. Add `GET /api/v1/trades/{id}` returning trade + linked AIDecision + decision event timeline + similar setups (pulled from Qdrant, capped 5).
2. Backend: `GET /api/v1/analytics/by-session`, `/by-hour`, `/holding-distribution`, `/portfolio` (the rich version). Cache 30–60 s in Redis.
3. Frontend: new route `/trades` — filterable list, CSV export, infinite-scroll/cursor pagination.
4. Frontend: new route `/trades/[id]` — detail page with mini lightweight-chart replaying entry → exit, MFE/MAE shading, decision timeline (vertical), similar setups table, "would-have-been-optimal-exit" overlay.
5. Frontend: new route `/analytics` — interactive equity curve, drawdown series, session heatmap, holding-time histogram (use lightweight-charts and recharts).
6. Timezone selector in user settings (`UTC` / `local` / explicit IANA), global formatter via `dayjs` plugin.
7. Wrap each major panel in `ErrorBoundary`. Add MUI Skeleton loading states.

---

### Phase 3 — Exit Optimization Engine
**Goal:** The user's primary trading-impact request.

1. New table `trade_decision_events` (migration + model + helper).
2. New service `app/services/exit_evaluator.py`:
   - `should_close_rules(trade, current_price, market_state) -> (close: bool, reason: str, confidence: float)`
   - `should_close_ai(trade, analysis) -> (recommendation, confidence, rationale)`
3. Extend `check_open_positions` to update price-path universally (some of this lands in Phase 1).
4. New Celery task `evaluate_exits` every 1 min: runs rule fast-path → if rule triggers, close + log event. Settings: `exit_optimization_enabled` (default `true` for rules), `profit_lock_giveback_pct` (default 50), `stale_holding_multiplier` (default 1.5), `news_window_min` (default 15).
5. New Celery task `ai_exit_reeval` every 5–10 min: alert-only initially. Setting `ai_exit_auto_execute` (default `false`). Setting `ai_exit_min_confidence` (default 0.6). Notifications via existing `notification_service`.
6. New endpoint `GET /api/v1/positions/{id}/exit-recommendation` — drives a UI badge on each open position (green=hold, amber=consider, red=close-now).
7. UI: live exit-recommendation badge in `PositionsPanel`. Notification toast when AI suggests close.

**Risk control:** Phase 3 ships with rules ON, AI alert-only. Single kill-switch setting `exit_optimization_enabled=false` reverts to pure SL/TP/trailing/EOD.

---

### Phase 4 — RAG Memory Loop
**Goal:** Close the AI feedback loop already half-built.

1. Wire `vs.search_similar()` into `run_full_analysis` entry decision path: retrieve top-10 similar past 90-day setups with min confidence threshold.
2. Compress retrieved setups into a 1–3 sentence summary, inject into AI prompt as `similar_setups_context`.
3. Mirror Qdrant points into `market_state_snapshots` SQL on every upsert, with FK to `ai_decisions(id)`.
4. Extend `update_outcome` post-close: store `exit_quality_score`, `mfe_pips`, `actual_holding_min`, `close_reason` in Qdrant payload AND SQL.
5. Nightly Celery `compute_pattern_priors`: per-pair × session × strategy stats cached in Redis for fast lookup; UI exposes via `/analytics/patterns`.
6. New endpoint `GET /api/v1/suggestions/{id}/explain` — RAG-grounded rationale, indicator weights, similar setups, scenarios, invalidation, expected holding.
7. UI: AI Suggestions cards become expandable showing the explain payload.

---

### Phase 5 — UX Polish & Institutional Layer
1. AI Suggestions card "Why" expandable using `/explain` payload.
2. Mobile responsive grid (stack on `< md`).
3. Implement real `correlation_guard` in `RiskManager.validate_ai_decision` — fetch open trades, pull pair correlation matrix (precomputed), reject if `|corr| > max_correlation_allowed`.
4. Drawing tools on chart (S/R lines, manual annotations) — defer if too costly.
5. Trade tagging + journal notes (Trade.notes column).
6. Custom dashboards — multi-watchlist + draggable layout (low priority unless user asks).
7. Light/dark theme toggle (low priority).

---

### Phase 6 — Continuous Learning & Backtest Loop
1. Nightly `rolling_backtest_30d` task → populate `backtest_runs` for trend telemetry.
2. Periodic `account_snapshot_writer` every 5 min. Stop wiping snapshots on `equity_balance` change — instead store `baseline_equity` and let drawdown be computed relative to current baseline.
3. Drift detector: alert if recent 30-trade WR diverges > 20% from 90-day average; suspend auto-trading if 60-trade WR < 35%.
4. Settings cache TTL → 30 s, or invalidate on every update for ALL keys (current code only invalidates for equity_balance).
5. Telemetry dashboard pulling from `backtest_runs` + `pair_performance_by_hour`.

---

## 6. Round 1 — Active Implementation Detail

### 6.1 Files to modify

| File | Change |
|---|---|
| `backend/app/models.py` | + 11 columns on `Trade` model |
| `backend/app/enums.py` | (no change — sessions stored as plain string) |
| `backend/app/services/sessions.py` | NEW — `classify_session_from_utc(dt) -> str` |
| `backend/app/services/execution/executor.py` | `execute_trade` stamps `session_at_open`; `close_trade` writes `close_reason`, `session_at_close`, `actual_holding_min`; price-path update extracted into helper called by ALL position-check paths |
| `backend/app/services/analytics_service.py` | NEW — `compute_portfolio_metrics(db) -> dict` and `compute_equity_curve(db) -> list` |
| `backend/app/main.py` | Replace metrics block in `/portfolio/summary` with call to `compute_portfolio_metrics`; add `/api/v1/analytics/equity-curve` endpoint |
| `backend/app/services/settings_service.py` | + `overnight_cutoff_enabled`, `overnight_cutoff_utc` defaults |
| `backend/app/tasks/analysis_tasks.py` | `_trading_paused` honors overnight cutoff |
| `backend/app/tasks/execution_tasks.py` | NEW task `close_overnight_cutoff` |
| `backend/app/celery_app.py` | + beat entry for `close_overnight_cutoff` every 5 min |
| `backend/init.sql` | + `ALTER TABLE` blocks for new columns + `CREATE INDEX` |
| `backend/migrate_round1.sql` | NEW — same statements, idempotent, applied to existing DB |
| `backend/app/tests/test_analytics.py` | NEW |
| `backend/app/schemas.py` | Extend `PortfolioSummaryOut`, `TradeOut`, `PositionOut` with new fields |
| `frontend/src/types/index.ts` | Extend `PortfolioSummary`, `Trade`, `Position` |
| `frontend/src/utils/sessions.ts` | NEW — JS classifier mirror |
| `frontend/src/utils/format.ts` | NEW — `formatNumber`, `formatPnl`, `formatDuration`, `formatSession`, `formatDateTime` |
| `frontend/src/components/ProfitMetricsPanel.tsx` | Fix falsy bug; render real sparkline |
| `frontend/src/components/PositionsPanel.tsx` | + open_time + session badge |
| `frontend/src/components/TradeHistoryPanel.tsx` | + close_time + duration + session + R-multiple + close_reason chip |
| `CHANGELOG.md` | + v0.9.0 entry |

### 6.2 New ORM column definitions (exact)

```python
# in app/models.py, class Trade:
close_reason          = Column(String(30))                    # already in DB
partial_tp_hit        = Column(Boolean, default=False)        # already in DB
partial_profit_pnl    = Column(Float)                          # already in DB
max_risk_amount       = Column(Float)                          # already in DB
mfe_pips              = Column(Float)                          # NEW
mae_pips              = Column(Float)                          # NEW
peak_pnl              = Column(Float)                          # NEW
peak_pnl_time         = Column(DateTime(timezone=True))        # NEW
session_at_open       = Column(String(20))                     # NEW
session_at_close      = Column(String(20))                     # NEW
actual_holding_min    = Column(Float)                          # NEW
```

### 6.3 Session classifier

```python
# app/services/sessions.py
SESSIONS = {
    "sydney":  (22, 7),    # wraps midnight
    "tokyo":   (0, 9),
    "london":  (7, 16),
    "ny":      (12, 21),
}

def classify_session(dt_utc) -> str:
    h = dt_utc.hour
    london_active = 7 <= h < 16
    ny_active     = 12 <= h < 21
    if london_active and ny_active:
        return "london_ny_overlap"
    if london_active:
        return "london"
    if ny_active:
        return "ny"
    if 0 <= h < 7:
        return "asian"
    return "sydney"
```

(JS mirror in `frontend/src/utils/sessions.ts`.)

### 6.4 Portfolio metrics rewrite (sketch)

```python
# app/services/analytics_service.py
async def compute_portfolio_metrics(db):
    rows = (await db.execute(
        select(models.Trade.pnl, models.Trade.pnl_pct, models.Trade.close_time)
        .where(models.Trade.status == models.TradeStatus.CLOSED)
        .order_by(models.Trade.close_time.asc())
    )).all()

    if not rows:
        return _empty_metrics()

    pnls = [r.pnl or 0.0 for r in rows]
    pcts = [r.pnl_pct or 0.0 for r in rows]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = (len(wins) / n) * 100
    avg_win = sum(wins)/len(wins) if wins else 0.0
    avg_loss = abs(sum(losses)/len(losses)) if losses else 0.0
    expectancy = (avg_win * len(wins)/n) - (avg_loss * len(losses)/n)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    # Equity curve from baseline equity_balance + cumulative PnL
    base = await get_setting_float(db, "equity_balance") or 0.0
    eq = []
    running = base
    for r, pnl in zip(rows, pnls):
        running += pnl
        eq.append((r.close_time, running))

    peak, max_dd = base, 0.0
    for _, e in eq:
        peak = max(peak, e)
        if peak > 0:
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd

    # Sharpe & Sortino on per-trade % returns, annualized for forex (~260 trading days)
    import statistics, math
    if n > 1:
        avg_ret = statistics.fmean(pcts)
        std_ret = statistics.pstdev(pcts) or 0.0
        sharpe = (avg_ret / std_ret) * math.sqrt(260) if std_ret > 0 else 0.0
        downside = [r for r in pcts if r < 0]
        downside_std = statistics.pstdev(downside) if len(downside) > 1 else 0.0
        sortino = (avg_ret / downside_std) * math.sqrt(260) if downside_std > 0 else 0.0
    else:
        sharpe = sortino = 0.0

    return {
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "expectancy": round(expectancy, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "equity_history": [{"timestamp": t.isoformat(), "equity": round(e, 2)} for t, e in eq],
    }
```

### 6.5 Verification commands (run before merge)

```bash
# Schema sanity
docker exec deez-forex-postgres psql -U forex -d deez_forex -c "\d trades" | grep -E "(mfe_pips|peak_pnl|session_at|close_reason)"

# Metric sanity (post-deploy)
curl -s http://localhost:28000/api/v1/portfolio/summary | jq '{max_drawdown_pct, sharpe_ratio, expectancy, total_trades}'

# Equity curve
curl -s http://localhost:28000/api/v1/analytics/equity-curve | jq '.[0:3]'

# Tests
cd backend && python -m pytest app/tests/test_analytics.py -v

# Live UI smoke (Playwright via skill or manual)
# Open https://fx.deeztechnology.solutions/ — confirm:
#   • Max Drawdown / Sharpe / Expectancy show non-zero numbers
#   • Sparkline renders below the metrics tiles
#   • Open Positions show open_time + session badge
#   • Trade History shows close_time + duration + session + close_reason chip
#   • Network log: no 429 errors
```

---

## 7. How to Resume in a Future Session

1. Read this file and `CHANGELOG.md` first.
2. `cd /home/mundeez/CascadeProjects/windsurf-project/deez-forex-ai && git status && git log --oneline -10`
3. Check active todos: search recent changes against §6.1's file list.
4. Health probe: `curl -s http://localhost:28000/api/v1/system/health | jq` and confirm AI is available + auto_trading status.
5. If Round 1 not yet shipped → continue at §6 against the file list and verification commands.
6. If Round 1 shipped → re-engage user to plan Round 2 (Phase 2 visibility/drilldown) per §5.
7. Respect §4 decisions; do not change exit autonomy or UI scope without re-asking.

---

## 8. Glossary

- **MFE** — Maximum Favorable Excursion: best unrealized profit reached during a trade.
- **MAE** — Maximum Adverse Excursion: worst unrealized loss reached during a trade.
- **R-multiple** — `realized_pnl / initial_risk` (where initial_risk = `|entry - SL| × position_size × pip_value`). 1R = "won as much as you risked".
- **Profit factor** — `gross_profit / gross_loss`.
- **Expectancy** — average $ per trade: `(avg_win × P_win) - (avg_loss × P_loss)`.
- **Sharpe** — `mean(returns) / std(returns) × sqrt(annualization)`. Forex annualization ≈ 260 trading days.
- **Sortino** — Sharpe variant using downside-only std.
- **Calmar** — `annual_return / max_drawdown`.
- **MFE-giveback** — `(peak_pnl - realized_pnl) / peak_pnl`. Higher = closed too late.
- **Session classification** — based on UTC hour: Asian 0–7, London 7–16 (overlap with NY 12–17), NY 12–21, Sydney 22–7.

---

*End of plan. Edits welcome — keep §4 (decisions) and §0 (snapshot) up-to-date as work progresses.*

# Changelog

All notable changes to Deez Forex AI will be documented in this file.

---

## [v1.8.0] — 2026-08-25

### Round 2 — Trade Visibility & Analytics

This release closes Round 2 with full trade visibility and analytics on both the backend and frontend, plus hardening and lint cleanup for the new frontend pages.

#### ✨ Added
- **Backend analytics endpoints**: `GET /api/v1/analytics/{portfolio,by-session,by-hour,holding-distribution}`, paginated `GET /api/v1/trades` with filters, sorting, and cursor pagination, and `GET /api/v1/trades/{id}` with linked AI decision and similar setups via vector search.
- **New backend schemas**: `TradeListResponse`, `TradeDetailOut`, `SimilarSetupOut`, `SessionAnalyticsOut`, `HourAnalyticsItem`, `HoldingBucketOut`.
- **Analytics service helpers**: `compute_analytics_by_session`, `compute_analytics_by_hour`, `compute_holding_distribution`, and overnight cutoff setting support.
- **Frontend analytics page** (`/analytics`) with portfolio metrics, equity curve chart via `lightweight-charts`, and by-session/by-hour/holding-distribution breakdowns.
- **Frontend trade history page** (`/trades`) with filterable, paginated trade history and CSV export.
- **Frontend trade detail page** (`/trades/[id]`) showing full trade detail, linked AI decision, and similar setups.
- **Overnight cutoff controls** on the `/settings` page and an **Analytics** link in the Header.
- **New frontend types**: `TradeListResponse`, `TradeDetail`, `SimilarSetup`, `SessionAnalytics`, `HourAnalytics`, `HoldingBucket`, plus `formatDateTime` helper and widened `formatSession`.
- **Strict ESLint config** (`next/core-web-vitals`) and **AbortController hardening** on `/trades` so stale fetches cannot overwrite newer results.

#### 🚨 Fixed
- Override transitive `glob` to `^10.4.6` to clear GHSA-5j98-mcp5-4vw2.
- Clear remaining `react-hooks/exhaustive-deps` warnings in `ChartPanel` live-price effect and `useWebSocket` `symbolsKey` ref pattern.
- Use `sqlalchemy.case` instead of `func.case` in analytics queries.
- Add missing `List` import in `main.py`.

#### ⚠️ Known Limitations
- Two remaining `npm` high vulnerabilities (`next`/`postcss`) require **Next.js 16** to resolve fully. They are pre-existing and documented in the previous release.

#### ⏭️ Skipped
- **Docker rebuild**: no `Dockerfile` or `compose` changes this phase.
- **Backend tests**: no new backend code changes in this closeout; backend was validated in the prior round-2 commits.
- **DB migrations**: none required.

---

## [v0.3.0] — 2026-08-23

### Round 1 — Live Portfolio Analytics, Trade Visibility, and Build-Typing Hardening

This release closes Round 1 with live portfolio analytics on the backend, richer trade visibility in the UI, execution-control settings, and a final build-typing hardening pass.

#### ✨ Added
- **Live portfolio analytics service** with equity-curve endpoint and portfolio summary API.
- **ProfitMetricsPanel** sparkline and live profit/loss metrics on the dashboard.
- **PositionsPanel** session badge and **TradeHistoryPanel** close-reason, session, duration, and R-multiple columns.
- **Overnight cutoff setting**, **analysis pause**, and a dedicated **close task** for execution control.
- **Analytics test suite** with deterministic, per-test cleanup.

#### 🚨 Fixed
- Dependency audit follow-up and **@types/jest** typing fix for the frontend build.

#### ⚠️ Known Limitations
- Two remaining `npm` high vulnerabilities require **Next.js 16** to resolve fully.

---

## [v1.7.0] — 2026-08-19

### Phase 0/1/2 — Live Signal Loop & Sentiment Repair

This release restores the live AI analysis loop and fixes the data sources that were causing every signal to abort or default to neutral.

#### 🚨 Fixed
- **Recurring `run_full_analysis` crash** — NumPy array truth-value error in the MT5 RPyC candle path (`mt5/mt5_service.py`) prevented all analysis.
- **Undefined `_decision_id` in HOLD branches** — news-halt and entry-gate HOLD paths now broadcast the committed `db_decision.id`.
- **Myfxbook 403 / empty retail sentiment** — `ingest_retail_sentiment` falls back to a COT-based `cot_proxy`, and `SentimentAnalyzer` uses the cached `retail_sentiment` row when live scraping fails.

#### ✨ Added
- **Qdrant hard-dependency gate** — `run_full_analysis` initializes and health-checks `AsyncVectorStore` before the analysis loop.
- **Per-symbol defensive aggregation** — a failure for one pair no longer aborts the entire `run_full_analysis` run.
- **Scheduled live data ingestion** — Celery beat now schedules:
  - `ingest_retail_sentiment` (every 30 minutes)
  - `ingest_forex_factory_calendar` (every hour)
  - `refresh_sentiment_cache` (every 30 minutes)
- **COT-based retail proxy** — `retail_sentiment` table backfilled from CFTC COT non-commercial positions.

#### 🔧 Changed
- `SentimentAnalyzer.analyze()` now uses live APIs in forward mode and only queries point-in-time DB tables for explicit backtest `as_of` timestamps.
- Paper equity reset to `$200` and `account_snapshots` truncated for a clean validation baseline.

#### 📋 Files Changed
- `mt5/mt5_service.py`
- `backend/app/services/data/mt5_rpyc_client.py`
- `backend/app/analysis/aggregator.py`
- `backend/app/tasks/analysis_tasks.py`
- `backend/app/analysis/sentiment.py`
- `backend/app/tasks/data_tasks.py`
- `backend/app/celery_app.py`
- `backend/app/services/vector_store.py`
- `docs/REVIVAL_AND_LEARNING_PLAN.md`

---

## [v0.7.2] — 2026-06-02

### Trade Closure Hotfix — Critical Bug Fixes

This release fixes **5 critical bugs** that prevented open trades from closing, causing positions to remain open for 38+ hours and turning profitable trades into losses.

#### 🚨 Fixed
- **Critical: Time-based trade close crashes every minute** — `datetime.utcnow()` (naive) subtracted from `trade.open_time` (timezone-aware) caused `TypeError`, crashing the `check_open_positions` Celery task. All 49 open trades were never evaluated for time-based exit.
- **Critical: SL/TP checked against wrong spread side** — BUY trades checked SL/TP against ask (should be bid), SELL trades checked against bid (should be ask). This made stops artificially harder to hit.
- **Critical: `close_time` assigned naive datetime to timezone-aware column** — `trade.close_time = datetime.utcnow()` could cause commit failures depending on driver behavior.
- **Reevaluation PnL always zero** — `trade.pnl_usd(...)` was called as a model method but `pnl_usd` is a module function in `app.services.instruments`. Profit-lock and stale-trade rules never triggered.
- **Reevaluation trade direction comparison failed** — `trade.direction.value == "buy"` compared string to enum, always false for some enum implementations.

#### 🔧 Changed
- **Unified UTC datetime helper** — New `app/utils/time.py` with `utc_now()` returns timezone-aware datetimes. Replaced all ~40 `datetime.utcnow()` calls across 13 files to prevent future naive/aware mismatches.

#### 📋 Files Changed
- `backend/app/utils/time.py` — New centralized helper
- `backend/app/services/execution/executor.py` — datetime fixes, spread-side SL/TP fix
- `backend/app/tasks/execution_tasks.py` — datetime fixes, pnl_usd fix, direction comparison fix
- `backend/app/tasks/analysis_tasks.py` — datetime fixes
- `backend/app/main.py` — datetime fixes
- `backend/app/backtest/engine.py` — datetime fixes
- `backend/app/backtest/optimizer.py` — datetime fixes
- `backend/app/ai/team/daily_bias.py` — datetime fixes
- `backend/app/services/settings_service.py` — datetime fixes
- `backend/app/services/news_service.py` — datetime fixes
- `backend/app/services/websocket_broadcaster.py` — datetime fixes
- `backend/app/analysis/fundamental.py` — datetime fixes
- `backend/app/suggestion_engine/engine.py` — datetime fixes
- `backend/app/services/sessions.py` — docstring update
- `backend/app/tests/test_close_reason.py` — timezone-aware test fixtures, 2 new tests

---

## [v0.7.0] — 2026-05-21

### AI Resilience & Auto-Trade Recovery

This release addresses a critical failure where the auto-trade system silently stopped working due to exhausted OpenRouter API credits (402 Payment Required). The entire analysis pipeline now has comprehensive error handling, fallback strategies, and operational visibility.

#### 🚨 Fixed
- **Critical: AI failure crashes entire analysis pipeline** — OpenRouter API errors (402, 404, 429, timeouts) are now caught and handled gracefully instead of crashing the task
- **Silent trading failure** — system now notifies the user when AI is unavailable for 3+ consecutive cycles
- **News date parsing bug** — ISO 8601 timestamps with timezone offsets (e.g. `2026-05-21T09:45:00-04:00`) now parse correctly
- **Qdrant point ID format error** — snapshot upserts no longer fail on non-UUID IDs

#### ✨ Added
- **AI Model Selection Dropdown** — choose from 7 models in Settings → AI tab, with hover tooltip descriptions for each
  - `nvidia/nemotron-3-super-120b-a12b:free` (default — zero cost, confirmed working)
  - `deepseek/deepseek-v4-flash:free` (zero cost, may be rate-limited)
  - `google/gemma-4-26b-a4b-it:free` (zero cost)
  - `google/gemini-2.5-flash` (cheap, best JSON mode)
  - `deepseek/deepseek-chat` (extremely cheap, excellent reasoning)
  - `openai/gpt-4o-mini` (cheap, reliable JSON)
  - `anthropic/claude-sonnet-4.5` (previous default, expensive)
- **Configurable AI Fallback Strategy** — when AI is unavailable:
  - `rule_based` — use EMA crossover + ADX + RSI technical rules
  - `pause_and_alert` — stop trading, notify user
  - `hold` — safe default, return HOLD for all pairs
- **Trade Aggressiveness Control** — conservative / moderate / aggressive modes adjust AI prompt tone and confidence thresholds
- **System Health API** — `GET /api/v1/system/health` returns AI availability, last analysis, current model, open positions, auto-trading status
- **Trade Decision Audit Logging** — structured `[AUDIT]` log entries trace every decision through the pipeline:
  ```
  [AUDIT] GBPUSD: AI=BUY(0.62) → Risk=OK → SL/TP=OK → EXECUTED(0.03 lots)
  [AUDIT] EURUSD: AI=BUY(0.48) → BLOCKED: confidence 0.48 < 0.40 threshold
  ```
- **System Alert Notifications** — critical/warning/info alerts via configured webhooks when AI fails

#### 🔧 Changed
- **Default model**: `anthropic/claude-sonnet-4.5` → `nvidia/nemotron-3-super-120b-a12b:free` (zero cost)
- **Default AI confidence threshold**: 0.60 → 0.40 (tuned for free model behavior)
- **Default fallback strategy**: `hold` → `rule_based` (active fallback instead of passive)
- **Default trade aggressiveness**: `moderate` → `aggressive` (prefer action during testing)
- **ADX threshold in prompts**: lowered from 20 to 15 (less conservative)
- **Model is now a DB-backed setting** — switch models at runtime without restart

#### 📋 Files Changed
- `backend/app/config.py` — default model, env config
- `backend/app/tasks/analysis_tasks.py` — try/except, fallback, audit logging, health tracking, rule-based decisions
- `backend/app/ai/openrouter_client.py` — model override, aggressiveness-aware prompts
- `backend/app/services/settings_service.py` — new DB-backed settings
- `backend/app/schemas.py` — new settings schema fields
- `backend/app/main.py` — system health API endpoint
- `backend/app/services/news_service.py` — ISO 8601 date parsing fix
- `backend/app/services/notification_service.py` — system alert method
- `frontend/src/app/settings/page.tsx` — model dropdown with tooltips, fallback & aggressiveness controls

---

## [v0.6.2] — Previous

- Fix analysis pipeline: Celery beat, async SQLAlchemy, numpy serialization
- Hotfix: add missing DataProvider import in main.py
- Fix frontend build: install missing deps and fix Python-style comments
- Phase 7: Testing & Code Quality
- Phase 6: UI/UX Overhaul with MUI (Part 1)
- Phase 8: Infrastructure & Deployment Hardening

---

[v1.8.0]: https://github.com/mundeez/deez-forex-ai/compare/v1.7.0...v1.8.0
[v0.3.0]: https://github.com/mundeez/deez-forex-ai/compare/v0.2.0...v0.3.0
[v0.7.0]: https://github.com/mundeez/deez-forex-ai/compare/v0.6.2...v0.7.0
[v0.6.2]: https://github.com/mundeez/deez-forex-ai/releases/tag/v0.6.2
# Changelog

All notable changes to Deez Forex AI will be documented in this file.

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

[v0.7.0]: https://github.com/mundeez/deez-forex-ai/compare/v0.6.2...v0.7.0
[v0.6.2]: https://github.com/mundeez/deez-forex-ai/releases/tag/v0.6.2
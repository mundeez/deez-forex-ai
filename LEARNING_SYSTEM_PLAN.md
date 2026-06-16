# Deez Forex AI — Self-Improvement & Learning System Implementation Plan

**Status:** APPROVED  
**Approved:** 2026-06-16  
**Target:** Live deployment on $200 account within 6–8 weeks  
**Timeline Mode:** Compressed (no phases deferred)  
**Data Budget:** Free sources only  
**Architecture Audited:** v0.9.0  

---

## How to Use This Document

- **§1–§2** — Architecture assessment and gap analysis (read-only context)
- **§3–§10** — Technical specifications per domain
- **§11** — Active implementation roadmap + Standard Sprint Close-Out Procedure
- **§12–§16** — Risk, cost, infrastructure, tools, models

Resume instructions:
1. Read this file and IMPROVEMENT_PLAN.md first
2. git log --oneline -10 to confirm current state
3. Find the current Sprint in §11 and continue from the first incomplete item
4. All acceptance criteria must pass before marking a Sprint complete

---

## 1. Architecture Assessment (Current State)

| Layer | Current Capability | Status |
|---|---|---|
| AI Decision Engine | 6-tier multi-agent pipeline (Daily Bias, 4 Analysts, Lead, Verifier) | Functional |
| Model Routing | Redis round-robin across 7 free OpenRouter models, paid fallback | Functional |
| Tick Ingestion | Dukascopy .bi5 binary download, gap detection, checkpoint-resume | Functional |
| Market Data | TimescaleDB continuous aggregates bars_1m to bars_1w | Functional |
| Vector Store | Qdrant 32-dim cosine similarity for market state snapshots | Partial |
| RAG | Lead Strategist queries similar past setups | Wired, feedback broken |
| Risk Management | Strategy-aware validation, ATR SL/TP, drawdown reduction tiers | Functional |
| Execution | Paper + Live via MT5 ZMQ/RPyC or MetaAPI, slippage simulation | Functional |
| Backtesting | Walk-forward engine with spread + commission | Skeleton (0 rows) |
| Exit Management | Mechanical SL/TP only — EXIT_REEVAL_ENABLED = False | Not live |
| Performance Learning | ModelPerformance + PairPerformanceByHour tables exist | Tables only |

---

## 2. Gap Analysis (P0 Critical)

**Gap 1 — Broken RAG Feedback Loop**
- analysis_tasks.py calls vs.upsert_snapshot() — OK
- executor.close_trade() does NOT call vs.update_outcome() — BROKEN
- Lead Strategist searches similar setups but gets outcome_pnl=None — BROKEN
- Fix: 2 code changes, ~2 hours

**Gap 2 — No AI Exit Re-Evaluation**
EXIT_REEVAL_ENABLED = False hardcoded. Empirical evidence from 179 trades:
- 0-5 min bucket: 47.4% WR (mechanical SL exits)
- 2-8 hour bucket: 87.5% WR (adequate holding time)
Exit timing is the primary profitability driver, not entry quality.

**Gap 3 — Position Sizing Broken for $200 Account**
position_size = risk_amt / (sl_dist * 100000) produces sub-0.01 lot sizes.
No minimum lot enforcement. Broker rejects these orders.

**Gap 4 — Data Poverty**
- Economic Events: ForexFactory titles only (no actual release values)
- Interest Rates: FRED partially wired, not systematically ingested
- Retail Sentiment: 100% mocked
- COT Data: 100% mocked
- Macro (DXY/VIX/bonds): not acquired at all
- News Sentiment: keyword matching only

**Gap 5 — Backtesting Never Runs**
backtest_runs table has 0 rows. No automatic scheduling.

---

## 3. Data Acquisition Strategy

### 3.1 Sources (all free)
- Dukascopy: 10 pairs, 5-year tick history (existing, needs backfill trigger)
- yfinance: DXY, VIX, S&P500, Gold, Crude, 10Y yield
- FRED API: 11 key series (fed funds, CPI, unemployment, yields, yield curve, VIX, ECB rate, breakeven inflation, HY spread)
- CFTC COT: https://www.cftc.gov/dea/options/deacmesf.htm (weekly CSV, free)
- Myfxbook: retail positioning API (free with account)
- FinBERT (ProsusAI/finbert): CPU-compatible local NLP model

### 3.2 New Tables Required (Sprint 1 migration)
- economic_events (timestamp, currency, event_name, actual, forecast, previous, surprise)
- cot_reports (report_date, symbol, nc_long, nc_short, nc_net, spec_pct_oi)
- retail_sentiment (timestamp, symbol, long_pct, short_pct, net_score)
- macro_series (timestamp, series_id, value, source)
- news_headlines (published_at, symbol, headline, finbert_positive, finbert_negative, composite_score)
- trade_patterns (trade_id, entry_regime, analyst_consensus, mfe_pips, mae_pips, r_multiple, exit_quality_score)
- market_regimes (timestamp, symbol, timeframe, regime, adx, bb_width_pct, confidence)

---

## 4. Learning Architecture

Three-layer hybrid (RAG + Supervised + RL deferred):

**Layer 1: RAG Memory (immediate)**
- Fix Qdrant feedback loop — wire update_outcome() after every close
- Lead Strategist retrieves top-10 similar past setups with outcomes
- Result: AI knows setups like this won X% of the time last month

**Layer 2: XGBoost Entry Gate (Sprint 4, ~week 4)**
- Trained on: technical features + analyst consensus + regime + session
- Label: R-multiple >= 0.8 = good entry
- Gate: if xgb_entry_score < 0.40, skip LLM team call entirely
- Needs 500+ labeled examples (179 existing + backtest replay)

**Layer 3: RL Exit Agent (deferred — post 2,000 live trades)**
- stable-baselines3 PPO on simulated Dukascopy tick environment
- Action space: HOLD / CLOSE / PARTIAL_CLOSE
- Reward: Sharpe-adjusted PnL

### 4.1 Qdrant Expansion: 32 -> 128 dimensions
New encoding adds: per-timeframe signals, fundamental scores, sentiment (FinBERT + COT + retail), macro (DXY z-score, VIX, yield curve), session cyclical encoding, regime labels.

Four collections:
1. market_state_snapshots (existing, expand to 128-dim)
2. exit_pattern_library (new, 64-dim)
3. analyst_performance_context (new, 32-dim)
4. regime_playbook (new, 32-dim)

---

## 5. Profitability Optimization

### 5.1 Exit Layer Architecture

Layer 1 — Rules (deterministic, ship Sprint 2):
- Profit lock: close if current_pnl < 50% of peak_pnl AND trade is profitable
- Staleness: close if holding > 1.5x strategy max duration
- Pre-news: close if high-impact event within 15 minutes
- Technical flip: close if price crosses EMA-9 against trade direction

Layer 2 — XGBoost exit model (Sprint 4):
- Input: MFE, MAE, unrealized PnL, time in trade, S/R distance, delta vector
- Output: probability(optimal_to_close_now)
- Gate: if score > 0.70 -> flag for AI review

Layer 3 — TradeManagerAgent LLM (Sprint 5):
- Returns: {action: HOLD|CLOSE|PARTIAL, confidence, reason}
- Prompt focus: Has the reason for this trade been invalidated?

### 5.2 Partial Profit Taking
- At 1R profit: close 33%, move SL to breakeven
- At 1.5R profit: close 33% more, trail remaining 34%
- Trail final 34% with 0.5 x ATR trailing stop

### 5.3 Dynamic SL Ladder
- 0.5R profit: move SL to entry (breakeven)
- 1.0R profit: move SL to 0.3R profit
- 1.5R profit: trail at 0.5 x ATR

### 5.4 Expected Impact
- Fix RAG feedback loop: +3-5% WR, +15-20% expectancy
- Profit lock at 50% giveback: +5-8% WR, +20-30% expectancy
- Breakeven stop at 0.5R: +3-5% WR, +10-15% expectancy
- Real COT + sentiment data: +3-6% WR, +12-18% expectancy
- XGBoost entry filter: +5-10% WR, +15-25% expectancy
- AI exit re-evaluation: +3-5% WR, +15-25% expectancy
- Partial profit taking: neutral WR, +15-20% expectancy
- Combined (conservative): +15-25% WR, +100-150% expectancy

---

## 6. Risk Management for $200 Account

### 6.1 Position Sizing Fix


### 6.2 Emergency Stops
- Daily loss > 3%: pause 24 hours (hard stop)
- Weekly loss > 6%: pause until next Monday (hard stop)
- Equity < $140 (30% DD): halt all entries, require manual review
- 3 consecutive losses: 30-minute cooling-off
- 5 consecutive losses: halt until daily bias refreshes (4 hours)

### 6.3 Account Growth Stages
| Stage | Equity | Risk/Trade | Max Concurrent |
|---|---|---|---|
| 0 — Seed | $200 | 1% | 2 |
| 1 — Grow | $500 | 1% | 2 |
| 2 — Scale | $1,000 | 1.5% | 3 |
| 3 — Compound | $5,000 | 1.5% | 3-4 |
| 4 — Institutional | $10,000+ | 2% | 4-5 |

Stage advance: win_rate >= 55% AND profit_factor >= 1.5 AND max_dd < 10% over last 50 trades.

---

## 7. Backtesting Framework

Anti-leakage rules:
- FRED data: point-in-time query only
- COT data: 3-day lag (released Friday for prior Tuesday)
- Economic events: release_time < candle_timestamp only
- Analysis warmup: 200 candles minimum before first signal

Walk-forward: 6-month train / 1-month validate / 1-month forward step
Success: >= 60% of windows show Profit Factor > 1.2; Sharpe std < 0.8

Monte Carlo: 5,000 bootstrap runs
Outputs: worst-case 95th pct drawdown, ruin probability (equity < $140), equity distribution

---

## 8. Validation KPIs

| KPI | Current | S2 Target | S4 Target | Live Target |
|---|---|---|---|---|
| Win Rate | 47.4% | 52% | 58% | 62% |
| Profit Factor | ~1.1 | 1.3 | 1.6 | 1.9 |
| Sharpe Ratio | N/A | 0.5 | 1.0 | 1.5 |
| Max Drawdown | Unknown | < 20% | < 15% | < 12% |
| RAG outcome coverage | 0% | 90% | 98% | 99% |
| Exit quality score | N/A | 0.55 | 0.65 | 0.70 |

---

## 9. New Python Dependencies



---

## 10. Recommended Models (Free Suite)

| Function | Model |
|---|---|
| Technical Analyst | openai/gpt-oss-120b:free |
| Fundamental Analyst | meta-llama/llama-3.3-70b-instruct:free |
| Sentiment Analyst | qwen/qwen3-next-80b-a3b-instruct:free |
| Macro Analyst | deepseek/deepseek-r1:free |
| Lead Strategist | openai/gpt-oss-120b:free |
| Verifier | deepseek/deepseek-r1:free |
| Trade Manager Agent | deepseek/deepseek-r1:free |
| Daily Bias | deepseek/deepseek-r1:free |

---

## 11. Implementation Roadmap (6–8 Week Compressed)

---


### Standard Sprint Close-Out Procedure

Every sprint ends with this mandatory four-step sequence.
**No sprint is complete until all four steps pass without errors.**

---

#### Step 1 — Rebuild All Docker Containers

```bash
# From project root
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up -d
sleep 30   # wait for health checks

# Verify all services are healthy
docker compose ps
# Expected: all containers show "healthy" or "running"
# Blockers: any container in "exit", "restarting", or missing
```

If any container fails to start:
- Check `docker compose logs <service>` for the error
- Fix the root cause in the relevant Dockerfile or config
- Rebuild that service: `docker compose build <service> && docker compose up -d <service>`
- Re-run the full health check before proceeding

---

#### Step 2 — Comprehensive Test Suite

Run all test categories in order. **Stop and fix on any failure before continuing.**

```bash
# 2a. Backend unit + integration tests
cd backend
python -m pytest tests/ -v --tb=short --timeout=120
# Required: 0 failures, 0 errors

# 2b. Backend type checking
python -m mypy app/ --ignore-missing-imports --no-error-summary
# Required: 0 errors (warnings acceptable)

# 2c. Backend linting
python -m flake8 app/ --max-line-length=120 --count
# Required: 0 errors (style warnings acceptable)

# 2d. API smoke tests — verify all critical endpoints respond
curl -sf http://localhost:8000/health || exit 1
curl -sf http://localhost:8000/api/v1/status || exit 1
curl -sf http://localhost:8000/api/v1/trades?limit=5 || exit 1
# Required: HTTP 200 on all endpoints

# 2e. Celery task smoke tests
docker compose exec celery celery -A app.celery_app inspect active
docker compose exec celery celery -A app.celery_app inspect registered
# Required: AI analysis tasks + data tasks visible and responsive

# 2f. Database migration verification
docker compose exec db psql -U postgres -d forex_ai -c "\dt" | grep -E "(trade|decision|macro|cot|regime)"
# Required: all new tables from current sprint exist

# 2g. Qdrant connectivity
curl -sf http://localhost:6333/collections || exit 1
# Required: HTTP 200, expected collections listed

# 2h. Redis connectivity
docker compose exec redis redis-cli ping
# Required: PONG

# 2i. Frontend build
cd ../frontend
npm run build 2>&1 | tail -20
# Required: "compiled successfully" or zero errors

# 2j. Frontend E2E / UI tests (Playwright)
npx playwright test --reporter=line
# Required: 0 failures
# If no E2E tests exist yet for new features: write at least one smoke test
# covering the new UI elements introduced in this sprint before close-out

# 2k. MT5 bridge health (if MT5 container running)
docker compose exec mt5 supervisorctl status zmq_bridge
# Required: zmq_bridge RUNNING
```

If any test category fails:
- Fix the failing code; do not skip or exclude tests
- Re-run the failing category in isolation until green
- Then re-run the full suite from 2a to confirm no regressions introduced

---

#### Step 3 — Git Commit, Version Tag, and GitHub Release

Run only after **all tests in Step 2 pass**.

```bash
cd /path/to/deez-forex-ai

# Stage all changes from this sprint
git add -A

# Verify nothing sensitive is staged
git diff --cached --name-only

# Commit with sprint summary message
git commit -m "$(cat <<EOF
feat(sprintN): <Sprint Title>

Summary of changes:
- <bullet 1>
- <bullet 2>
- <bullet 3>

Acceptance criteria met:
- <criterion 1>
- <criterion 2>

Sprint close-out: Docker rebuild passed, all tests green.

Generated with Devin (https://cli.devin.ai/docs)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
EOF
)"

# Tag the release (version assigned per sprint — see table below)
git tag -a vX.Y.Z -m "Release vX.Y.Z — <Sprint Title>"

# Push commit and tag to GitHub
git push origin main
git push origin vX.Y.Z

# Create GitHub release with full notes
gh release create vX.Y.Z \
  --title "vX.Y.Z — <Sprint Title>" \
  --notes "$(cat <<EOF
## vX.Y.Z — <Sprint Title>

### What changed
<bullet points of every task completed in this sprint>

### Acceptance criteria met
<every criterion from the sprint, with pass/fail>

### Test results
- Backend unit tests: PASS
- Type checking: PASS
- Linting: PASS
- API smoke tests: PASS
- Celery tasks: PASS
- DB migrations: PASS
- Frontend build: PASS
- Playwright E2E: PASS

### Known limitations / deferred items
<any items explicitly deferred to a later sprint>

### Next sprint
<name and goal of the next sprint>
EOF
)"
```

---

#### Step 4 — Move to Next Sprint

Only after the GitHub release is live:
1. Update the `Done` column checkbox to `[x]` for all completed tasks in §11
2. Update the sprint's status header from `[ ]` to `[COMPLETE — vX.Y.Z]`
3. Begin the next sprint's first task

---

### Version Tag Assignments

| Sprint | Version | Title |
|---|---|---|
| Baseline (audited) | v0.9.0 | Architecture Audit Baseline |
| Sprint 1 | v1.0.0 | P0 Fixes + Data Foundation |
| Sprint 2 | v1.1.0 | Exit Optimization Layer |
| Sprint 3 | v1.2.0 | Enhanced Analyst Data Inputs |
| Sprint 4 | v1.3.0 | Supervised Learning Pipeline |
| Sprint 5 | v1.4.0 | Backtesting + AI Exit Agent |
| Sprint 6 | v1.5.0 | Paper Trading Validated |
| Sprint 7 | v1.6.0 | Live Deployment ($200 Account) |
| Sprint 8+ | v1.7.x+ | Continuous Learning Iterations |

---

### Sprint 1 — Week 1: P0 Fixes + Data Foundation

**Goal:** Fix the three critical blockers and lay data infrastructure.

| # | Task | File(s) | Est. | Done |
|---|---|---|---|---|
| 1.1 | Wire update_outcome() in executor.close_trade() | services/execution/executor.py | 2h | [ ] |
| 1.2 | Populate market_state_snapshots SQL table on every Qdrant upsert | tasks/analysis_tasks.py | 2h | [ ] |
| 1.3 | Store qdrant_point_id back on AIDecision record | tasks/analysis_tasks.py, models.py | 1h | [ ] |
| 1.4 | Fix micro-lot position sizing (0.01 minimum enforcement) | services/risk/manager.py | 2h | [ ] |
| 1.5 | Add $200 emergency stops (daily/weekly/drawdown halt) | services/risk/manager.py, tasks/execution_tasks.py | 3h | [ ] |
| 1.6 | Create 7 new tables via Sprint 1 migration | backend/migrate_sprint1.sql, models.py | 4h | [ ] |
| 1.7 | Build FRED ingestion service (11 key series) | services/data/fred_client.py (new) | 4h | [ ] |
| 1.8 | Build CFTC COT downloader + weekly Celery task | services/data/cot_client.py (new) | 4h | [ ] |
| 1.9 | Build yfinance macro ingestion (DXY, VIX, yields, indices) | services/data/macro_client.py (new) | 3h | [ ] |
| 1.10 | Trigger Dukascopy 5-year backfill for all 10 pairs | tasks/data_tasks.py | 1h | [ ] |
| 1.11 | Expand Qdrant vector encoding 32 -> 128 dimensions | services/vector_store.py | 4h | [ ] |
| 1.12 | Implement RegimeDetector class | services/regime_detector.py (new) | 3h | [ ] |
| 1.13 | Attach regime label to every new AIDecision | tasks/analysis_tasks.py | 1h | [ ] |

**Acceptance Criteria:**
- qdrant_point_id and close_reason populated on all new closed trades
- update_outcome() called after every trade close (audit Qdrant payload)
- Position size computation rejects sub-0.01 lots for all symbol types
- Emergency stops tested: daily-loss halt fires at 3%
- macro_series, cot_reports, economic_events tables contain data rows
- Dukascopy backfill running (verify via ingestion_state table)

---


#### Sprint 1 Close-Out

```
Step 1: docker compose down --no-deps && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite (2a–2k above). Blockers to resolve before tagging:
        - All 7 new DB tables present and queryable
        - FRED/COT/yfinance services return rows (not empty)
        - Qdrant 128-dim collection exists and accepts vectors
        - Position size floor 0.01 enforced (unit test required)
        - Emergency stop logic covered by at least 2 unit tests
Step 3: git tag v1.0.0 — "P0 Fixes + Data Foundation"
Step 4: Begin Sprint 2
```

**Status: [ ] PENDING**

---
### Sprint 2 — Week 2: Exit Optimization Layer

**Goal:** Rules-based exit layer and partial profit taking.

| # | Task | File(s) | Est. | Done |
|---|---|---|---|---|
| 2.1 | Build ExitEvaluator service with rules layer | services/exit_evaluator.py (new) | 5h | [ ] |
| 2.2 | Profit-lock rule | services/exit_evaluator.py | 2h | [ ] |
| 2.3 | Staleness rule | services/exit_evaluator.py | 1h | [ ] |
| 2.4 | Pre-news exit rule | services/exit_evaluator.py | 2h | [ ] |
| 2.5 | Technical flip rule (EMA-9 cross) | services/exit_evaluator.py | 2h | [ ] |
| 2.6 | Celery task: evaluate_exits every 60 seconds | tasks/execution_tasks.py | 2h | [ ] |
| 2.7 | Settings: exit_rules_enabled, profit_lock_giveback_pct (default 50) | services/settings_service.py | 1h | [ ] |
| 2.8 | Breakeven stop: move SL to entry at 0.5R profit | services/execution/executor.py | 2h | [ ] |
| 2.9 | Dynamic SL ladder: 0.5R breakeven, 1.0R to 0.3R profit | services/execution/executor.py | 2h | [ ] |
| 2.10 | Partial profit taking: 33% at 1R, 33% at 1.5R, trail 34% | services/execution/executor.py | 3h | [ ] |
| 2.11 | Track exit_quality_score on all closed trades | services/execution/executor.py, models.py | 1h | [ ] |
| 2.12 | Endpoint: GET /api/v1/positions/{id}/exit-recommendation | main.py | 1h | [ ] |
| 2.13 | Frontend: exit recommendation badge on PositionsPanel | frontend/src/components/PositionsPanel.tsx | 2h | [ ] |

**Acceptance Criteria:**
- evaluate_exits fires every 60s without errors
- Paper trade hits 1R -> SL moves to entry
- Paper trade rises to 2R then drops to 0.9R -> profit-lock fires
- exit_quality_score populated on all trades closed after sprint
- Exit badge visible on PositionsPanel

---


#### Sprint 2 Close-Out

```
Step 1: docker compose down --no-deps && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite. Blockers:
        - evaluate_exits Celery task registered and fires on schedule
        - Paper trade profit-lock integration test passes
        - Breakeven SL logic covered by unit test
        - exit_quality_score column present on trades table
        - Frontend build and Playwright smoke test for exit badge pass
Step 3: git tag v1.1.0 — "Exit Optimization Layer"
Step 4: Begin Sprint 3
```

**Status: [ ] PENDING**

---
### Sprint 3 — Week 3: Enhanced Analyst Data Inputs

**Goal:** Replace all mocked data with real data.

| # | Task | File(s) | Est. | Done |
|---|---|---|---|---|
| 3.1 | Deploy FinBERT locally; build batch headline scorer | services/data/finbert_scorer.py (new) | 4h | [ ] |
| 3.2 | Celery task: nightly FinBERT scoring of unprocessed headlines | tasks/data_tasks.py | 2h | [ ] |
| 3.3 | Wire Myfxbook retail positioning into SentimentAnalyzer | analysis/sentiment.py | 3h | [ ] |
| 3.4 | Wire CFTC COT data into SentimentAnalyzer | analysis/sentiment.py | 2h | [ ] |
| 3.5 | Replace keyword sentiment with FinBERT composite score | analysis/sentiment.py | 2h | [ ] |
| 3.6 | Build MacroAnalyzer with DXY, VIX, yield curve, risk-on composite | analysis/macro.py (new) | 5h | [ ] |
| 3.7 | Wire MacroAnalyzer into AnalysisAggregator.gather_all() | analysis/aggregator.py | 1h | [ ] |
| 3.8 | Wire actual economic event values into FundamentalAnalyzer | analysis/fundamental.py | 3h | [ ] |
| 3.9 | Add economic surprise index to FundamentalAnalyzer output | analysis/fundamental.py | 2h | [ ] |
| 3.10 | Add Ichimoku + Stochastic + CCI to TechnicalAnalyzer via pandas-ta | analysis/technical.py | 4h | [ ] |
| 3.11 | Extend _technical_block() in DomainAnalyst | ai/team/analyst.py | 2h | [ ] |
| 3.12 | Extend _macro_block() in DomainAnalyst with real macro data | ai/team/analyst.py | 2h | [ ] |
| 3.13 | Extend Daily Bias macro_snapshot with DXY, VIX, COT, surprise index | ai/team/daily_bias.py | 2h | [ ] |

**Acceptance Criteria:**
- SentimentAnalyzer returns real retail positioning and COT net (not mocked)
- FundamentalAnalyzer returns actual event values + surprise index
- AIDecision.macro_snapshot_json contains DXY + VIX + yield curve
- FinBERT pipeline processes all unscored headlines nightly

---


#### Sprint 3 Close-Out

```
Step 1: docker compose down --no-deps && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite. Blockers:
        - SentimentAnalyzer.analyze() integration test returns real COT + retail data (not mocked)
        - FundamentalAnalyzer returns non-null actual/forecast fields
        - MacroAnalyzer returns DXY + VIX + yield curve (assert non-null)
        - FinBERT nightly task runs without OOM on available RAM
        - No regressions in existing analyst unit tests
Step 3: git tag v1.2.0 — "Enhanced Analyst Data Inputs"
Step 4: Begin Sprint 4
```

**Status: [ ] PENDING**

---
### Sprint 4 — Week 4: Supervised Learning Pipeline

**Goal:** Build and deploy XGBoost entry quality filter.

| # | Task | File(s) | Est. | Done |
|---|---|---|---|---|
| 4.1 | Build FeatureStore: compute_entry_features(), export_training_set() | services/feature_store.py (new) | 6h | [ ] |
| 4.2 | Historical trade labeler for all 179 existing trades | scripts/label_historical_trades.py (new) | 4h | [ ] |
| 4.3 | Backtest replay to generate 1,000+ additional labeled samples | scripts/generate_training_data.py (new) | 5h | [ ] |
| 4.4 | Train XGBoost entry quality classifier with cross-validation | services/ml/entry_model.py (new) | 4h | [ ] |
| 4.5 | Evaluate: precision, recall, OOS AUC | services/ml/entry_model.py | 2h | [ ] |
| 4.6 | Serialize model with joblib + store version in Redis | services/ml/entry_model.py | 1h | [ ] |
| 4.7 | Wire entry gate: skip LLM if xgb_entry_score < 0.40 | tasks/analysis_tasks.py | 2h | [ ] |
| 4.8 | Build PatternExtractor class | services/pattern_extractor.py (new) | 5h | [ ] |
| 4.9 | Nightly Celery task: compute_pattern_priors | tasks/analysis_tasks.py | 2h | [ ] |
| 4.10 | Build AnalystWeightOptimizer: weights per regime + session | services/analyst_weight_optimizer.py (new) | 4h | [ ] |
| 4.11 | Wire analyst weights into LeadStrategist prompt construction | ai/team/lead.py | 2h | [ ] |
| 4.12 | Populate ModelPerformance table via hourly update task | tasks/analysis_tasks.py | 2h | [ ] |
| 4.13 | Enable MODEL_PERF_WEIGHTING_ENABLED = True | config.py | 0.5h | [ ] |

**Acceptance Criteria:**
- XGBoost entry model achieves OOS AUC >= 0.60
- Entry gate fires: low-score decisions skipped in analysis task logs
- pattern_priors Redis key populated after compute_pattern_priors runs
- model_performance table has rows after one hour of trading
- Analyst weights differ between trending and ranging regimes

---


#### Sprint 4 Close-Out

```
Step 1: docker compose down --no-deps && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite. Blockers:
        - XGBoost model artifact present in /models/ or Redis key
        - Entry gate integration test: low-score signal correctly skipped
        - OOS AUC >= 0.60 (logged in test output)
        - compute_pattern_priors task runs without errors
        - ModelPerformance table receives rows after 1 artificial decision
        - Analyst weights differ between "trending" and "ranging" regimes (unit test)
Step 3: git tag v1.3.0 — "Supervised Learning Pipeline"
Step 4: Begin Sprint 5
```

**Status: [ ] PENDING**

---
### Sprint 5 — Week 5: Backtesting + AI Exit Agent

**Goal:** Professional backtesting framework and Trade Manager Agent.

| # | Task | File(s) | Est. | Done |
|---|---|---|---|---|
| 5.1 | Build DataLeakageGuard class | backtest/data_guard.py (new) | 3h | [ ] |
| 5.2 | Build WalkForwardTester (6-month train / 1-month test) | backtest/walk_forward.py (new) | 5h | [ ] |
| 5.3 | Build MonteCarloSimulator (5,000 bootstrap runs) | backtest/monte_carlo.py (new) | 4h | [ ] |
| 5.4 | Build RegimeBacktester for 5 regime periods | backtest/regime_tester.py (new) | 3h | [ ] |
| 5.5 | Build NewsEventBacktester for FOMC/NFP/ECB/CPI | backtest/news_tester.py (new) | 3h | [ ] |
| 5.6 | Extend BacktestRun model with backtest_type, regime, MC fields | models.py, migrate_sprint5.sql | 1h | [ ] |
| 5.7 | Nightly Celery task: rolling_backtest_30d | tasks/analysis_tasks.py | 2h | [ ] |
| 5.8 | Monthly Celery task: walk_forward_monthly | tasks/analysis_tasks.py | 1h | [ ] |
| 5.9 | Build TradeManagerAgent (LLM-based exit agent) | ai/team/trade_manager.py (new) | 5h | [ ] |
| 5.10 | Integrate TradeManagerAgent into evaluate_exits (alert-only mode) | tasks/execution_tasks.py | 2h | [ ] |
| 5.11 | Settings: exit_ai_enabled (default false), exit_ai_min_confidence (0.65) | services/settings_service.py | 0.5h | [ ] |
| 5.12 | System Intelligence Dashboard backend endpoints | main.py | 4h | [ ] |
| 5.13 | Frontend: /system route — AI performance + learning + backtest telemetry | frontend/src/app/system/page.tsx (new) | 5h | [ ] |

**Acceptance Criteria:**
- rolling_backtest_30d runs without errors; row inserted into backtest_runs
- Walk-forward: >= 55% of windows show PF > 1.2
- Monte Carlo: ruin probability (equity < $140) <= 10%
- TradeManagerAgent fires alerts and logs to trade_decision_events
- System dashboard accessible at /system

---


#### Sprint 5 Close-Out

```
Step 1: docker compose down --no-deps && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite. Blockers:
        - rolling_backtest_30d task completes and inserts row into backtest_runs
        - Walk-forward test over available history: >= 55% of windows PF > 1.2
        - Monte Carlo ruin probability <= 10% on current equity curve
        - TradeManagerAgent returns valid JSON action (HOLD/CLOSE/PARTIAL) in unit test
        - /system dashboard route returns HTTP 200 and renders without JS errors
Step 3: git tag v1.4.0 — "Backtesting + AI Exit Agent"
Step 4: Begin Sprint 6
```

**Status: [ ] PENDING**

---
### Sprint 6 — Weeks 6–7: Paper Trading Validation (30 Days)

**Goal:** Monitor full enhanced system on paper. No code changes.

Configuration:
- DECISION_ENGINE_VERSION=v2
- EXIT_RULES_ENABLED=true
- EXIT_AI_ENABLED=false (alert-only)

Daily monitoring KPIs:
- Win rate: target >= 52% by end of week 1
- Exit quality score: target >= 0.55
- RAG outcome coverage: target >= 90%
- XGBoost gate filter rate: target 15–30%
- Emergency stops: not triggered

Day-15 checkpoint:
- Win rate < 48%: investigate rejection reasons, adjust analyst weights
- Exit quality < 0.50: lower profit-lock threshold to 40%
- XGBoost gate > 50%: re-evaluate model threshold

End-of-sprint go/no-go gate:
- Win rate >= 52% over >= 100 paper trades
- Profit factor >= 1.2
- No single-day drawdown > 3%
- Exit quality score >= 0.55
- Zero uncaught exceptions for 7 consecutive days

---


#### Sprint 6 Close-Out

```
Step 1: No new code changes expected. Rebuild to confirm system unchanged:
        docker compose down && docker compose up -d
Step 2: Run full test suite. Confirm no regressions introduced during monitoring period.
        Additionally verify paper trading telemetry:
        - >= 100 paper trades in trades table
        - Win rate >= 52% (query: SELECT COUNT(*), AVG(CASE WHEN outcome='win' THEN 1 ELSE 0 END) FROM trades WHERE mode='paper')
        - Profit factor >= 1.2
        - No single-day drawdown > 3%
        - exit_quality_score average >= 0.55
        - Zero unhandled exceptions in celery/backend logs over last 7 days
Step 3: git tag v1.5.0 — "Paper Trading Validated"
Step 4: Begin Sprint 7 (Live Deployment)
```

**Status: [ ] PENDING**

---
### Sprint 7 — Week 7–8: Live Deployment ($200)

| # | Task | Est. | Done |
|---|---|---|---|
| 7.1 | Fund broker account: $200 | manual | [ ] |
| 7.2 | Set TRADE_MODE=live for EURUSD and GBPUSD only | config | [ ] |
| 7.3 | Verify all emergency stops in live environment | 2h | [ ] |
| 7.4 | Confirm 0.01 lot minimum fires correctly | 1h | [ ] |
| 7.5 | Keep paper trading running in parallel for drift comparison | config | [ ] |
| 7.6 | Week 1: max 2 concurrent trades, EURUSD + GBPUSD only | config | [ ] |
| 7.7 | Week 2: if net positive add USDJPY | config | [ ] |
| 7.8 | Week 3: if equity > $210 enable partial profit taking | config | [ ] |
| 7.9 | Week 4: Stage 0 -> Stage 1 gate check | review | [ ] |

**Acceptance Criteria:**
- Equity remains above $140 after 30 days
- At least 40 live trades executed in first 30 days
- Live win rate within 5% of paper trading baseline
- All emergency stops verified active

---


#### Sprint 7 Close-Out

```
Step 1: docker compose down && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite. Additional live deployment checks:
        - Live broker connection verified (MT5 ZMQ or MetaAPI ping returns OK)
        - TRADE_MODE=live confirmed for EURUSD + GBPUSD only
        - Emergency stops verified active in live environment
        - Paper trading still running in parallel (confirm paper trades being logged)
        - Live win rate within 5% of paper baseline after first 20 trades
Step 3: git tag v1.6.0 — "Live Deployment ($200 Account)"
Step 4: Transition to Sprint 8 Continuous Learning Loop
```

**Status: [ ] PENDING**

---
### Sprint 8 — Ongoing: Continuous Learning Loop

Perpetual tasks:
- Weekly: XGBoost retraining on rolling 90-day labeled dataset
- Nightly: compute_pattern_priors (winning/losing pattern update)
- Monthly: walk_forward_monthly (strategy drift detection)
- Drift alert: if 30-trade WR drops > 15% from 90-day baseline, pause entries

Post-1,000 live trades:
- Enable RL exit agent training (stable-baselines3 PPO)
- Stage 1 ($500) criteria review
- Add 2 additional currency pairs

---

## 12. Technical Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| XGBoost overfitting | High | Medium | max_depth=4, early stopping, OOS evaluation, min 500 samples |
| Free OpenRouter degraded | High | High | Paid fallback already implemented |
| Dukascopy data gaps | Medium | High | Gap detection + MT5 ZMQ supplement |
| Verifier too conservative | Medium | High | Track verifier_effectiveness; adjust verifier_can_veto |
| Backtest overfitting | High | Very High | Walk-forward + OOS + regime diversification |
| $200 account blown | Medium | Very High | Strict emergency stops; paper gate before live |
| Data leakage | Medium | Very High | DataLeakageGuard; COT 3-day lag; FRED point-in-time |

---

## 13. Cost

All new data sources: $0/month (FRED, CFTC, yfinance, Myfxbook, FinBERT — all free).

Development: ~41 engineer-days total to live deployment.

---

## 14. Glossary

- MFE — Maximum Favorable Excursion (best unrealized profit during a trade)
- MAE — Maximum Adverse Excursion (worst unrealized loss during a trade)
- R-multiple — realized_pnl / initial_risk
- Exit quality score — realized_pnl / mfe_pips (1.0 = closed at peak)
- Profit factor — gross_profit / gross_loss
- COT — Commitment of Traders (CFTC weekly institutional positioning report)
- FinBERT — Financial domain BERT model for sentiment classification
- XGBoost — Gradient boosted tree ensemble for tabular ML
- Walk-forward — Rolling train/test split simulating real-time deployment
- Stage gate — Automated criteria check before scaling account risk

---

*End of plan. Authoritative source for the learning system build.
Update §11 Sprint items as work completes. Do not modify §1–§10 without re-auditing the codebase.*

#### Sprint 8 Close-Out (Per Iteration)

Each continuous learning iteration (approximately monthly) follows the same procedure:

```
Step 1: docker compose down && docker compose build --no-cache && docker compose up -d
Step 2: Run full test suite. Additional checks:
        - XGBoost model retrained successfully (new artifact timestamp updated)
        - Retrained model OOS AUC >= 0.60
        - walk_forward_monthly completed and result row inserted
        - No drift alert triggered in last 7 days
Step 3: git tag v1.7.N — "Continuous Learning Iteration N"
        (increment N with each monthly iteration)
Step 4: Continue monitoring; trigger next iteration at month end
```

**Status: [ ] ONGOING**

---

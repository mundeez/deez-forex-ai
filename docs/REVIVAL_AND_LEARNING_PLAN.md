# FX DEEZ — Revival, Profitability & Learning Implementation Plan

**Status:** Draft — awaiting approval before execution  
**Created:** 2026-08-19  
**Target:** Restore live paper trading, make the system learn from every win/loss, and move the P&L curve toward profitability on the $200 seed account.  

---

## 1. What I Found (Investigation Summary)

### 1.1 The trading signal is broken
- `run_full_analysis` (the 30-minute Celery task that decides whether to enter trades) is crashing **every single run** with `ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()`.
- The traceback points to the MT5 RPyC service's `exposed_get_candles` method (`mt5/mt5_service.py:111`) where it evaluates `if not rates or len(rates) == 0` on a NumPy array returned by `mt5.copy_rates_from_pos`.
- Because the analysis task crashes, **no new `ai_decisions` records are created, no trades are opened**, and the system has been idle for roughly three weeks (last closed trade: 2026-07-28).

### 1.2 Learning is starved
- The `train_multitimeframe_and_team` retraining task requires **100 closed trades with an `ai_decision_id`**. It is **not scheduled in Celery beat**, so even if trades were occurring, it would not retrain automatically.
- `AnalystWeightOptimizer` and `model_perf_weighting` are effectively dormant because `model_perf_weighting_enabled` is `false` in settings and no new outcomes are being generated.
- The Qdrant `update_outcome` call is wired into `close_trade`, but the Qdrant instance is not reachable from the host and the vector store is not being used to retrieve similar setups during entry (`_memory_guard` is in the code but depends on a healthy Qdrant + outcome-populated collection).

### 1.3 Live data is missing
- `SentimentAnalyzer.analyze` takes a `db` session and therefore follows the **DB-only backtest path** during live `run_full_analysis`. The `retail_sentiment` and `news_headlines` tables are not being populated by scheduled live scrapers, so the AI receives neutral/0.0 sentiment and defaults to `HOLD`.
- `forex_factory` (`ff_client.py`) and `retail_client.py` ingestion tasks exist but are **not in `celery_app.py` beat_schedule**.
- `evaluate_exits` (the rule-based exit layer) is registered as a Celery task but is **not scheduled**, and `exit_reeval_enabled` is `false`.

### 1.4 Current P&L is underwater
Current live stats (`/api/v1/trades/stats`, 2026-08-19):

| Metric | Value |
|---|---|
| Equity | $188.88 |
| Realized P&L | -$11.12 |
| Total trades (since reset) | 39 |
| Win rate | 35.9% |
| Profit factor | 0.3 |
| Expectancy | -$0.29 |
| Last trade | 2026-07-28 |

This is a negative-expectancy system. Simply restoring the old behaviour will keep it losing money. Any restart must be paired with **calibrated entry/exit rules and a learning loop that adapts to outcomes**.

---

## 2. Root Causes (why trades stopped and why it isn't learning)

1. **MT5 RPyC candle bug** (`mt5/mt5_service.py:111`) crashes the data layer, which kills `run_full_analysis`.
2. **No live sentiment/news feed** because `SentimentAnalyzer` is forced into the DB path and the live scrapers are not scheduled.
3. **AI confidence collapses to 0.0** when the `Verifier`/`Lead` pipeline has stale context, producing `HOLD`.
4. **No scheduled retraining** — `train_multitimeframe_and_team` is not in the beat schedule.
5. **Exit rules are dormant** — `evaluate_exits` is not scheduled and `exit_reeval_enabled` is `false`; trades die only by mechanical SL/TP or time.
6. **Model performance weighting is disabled** — the system does not learn which analyst/model is currently best.
7. **Qdrant is not reachable** from the host; the RAG memory guard cannot veto bad setups or retrieve similar past outcomes.

---

## 3. Gaps Left Over From Prior Plans

### 3.1 `IMPROVEMENT_PLAN.md` (Round 1 was partially done)
- `Trade` model now has the Phase 1 fields, but the dashboard/frontend profit metrics are still broken in places.
- Price-path (`highest_price_seen` / `lowest_price_seen`) is recorded, but `peak_pnl_time` is still often `null`.
- `portfolio_summary` still pulls from `backtest_runs` in some places, which is empty.
- The RAG `search_similar` call is present in `_memory_guard` but Qdrant is not operational.

### 3.2 `LEARNING_SYSTEM_PLAN.md` (Sprints 1-5 not completed)
- Sprint 1: `update_outcome()` is wired, but `qdrant_point_id` is set and the 128-dim collection may not exist because Qdrant is down.
- Sprint 1: Retail / ForexFactory / Myfxbook live ingestion is not scheduled.
- Sprint 2: `ExitEvaluator` exists but is not wired into the execution loop on a schedule.
- Sprint 3: FinBERT and live news ingestion are not scheduled.
- Sprint 4: `EntryQualityModel` and `TeamMetaModel` training exist but are not scheduled.
- Sprint 5: Backtesting is correctly treated as validation-only per `AGENTS.md`.

### 3.3 `docs/backtest_data_and_engine_plan.md`
- FRED data is flowing; COT is now in the DB; economic events still need full live ingestion.
- The `as_of` parameters for backtest were added, which is good for future walk-forward validation.

---

## 4. Decisions Captured

These decisions were confirmed on 2026-08-19. They are now locked into the implementation roadmap.

| # | Decision | Your choice | Rationale / why it was selected |
|---|---|---|---|
| 1 | **Data feed for live analysis** | Fix MT5 RPyC | The crash is a one-line NumPy comparison bug in `mt5/mt5_service.py:111`. Fixing it restores the current pipeline fastest. |
| 2 | **Restart budget / reset** | Reset seed to $200 | Removes the -$11.12 drift and gives a clean, known equity baseline for KPIs. |
| 3 | **Confidence / trade frequency** | Balanced / collect data | Lower AI confidence threshold slightly, keep rule-based fallback, cap risk at 1% per trade. This is the fastest way to generate the 50+ labeled samples the meta-models need. |
| 4 | **Exit automation** | Auto-execute rules | The `ExitEvaluator` is already implemented. The current 35.9% win rate is partly caused by mechanical-only exits; auto-exit rules can improve expectancy immediately. |
| 5 | **Learning source** | Historical AI-decision trades | Use the pre-reset closed trades that already have `ai_decision_id`. These are real live outcomes, not backtest labels, so they bootstrap the models without violating the validation-only backtest rule. |
| 6 | **Qdrant / RAG memory guard** | Hard dependency | Qdrant must be healthy and the 128-dim `market_state_snapshots` collection created before the live analysis loop is restored. This means Phase 1 is gated on Qdrant. |
| 7 | **Live forward vs. backtest** | 1-week paper forward | Backtest is validation-only per `AGENTS.md`. A short live paper run with a hard stop is the only honest proof of edge. |

**Note on Decision 6 (Qdrant hard dependency):** You overrode my recommendation here. I had suggested making Qdrant optional so the signal loop could be restored faster. The approved plan now requires Qdrant to be fixed *before* any live analysis runs. I have moved the Qdrant repair to Phase 0/1 accordingly.

---

## 5. High-Level Suggestions (What I Would Do)

### 5.1 Restore the signal first
- Hot-fix the MT5 RPyC NumPy bug, or switch the data provider to a working feed so `run_full_analysis` stops crashing.
- Add defensive null/empty handling in `AnalysisAggregator` so one bad data provider cannot kill the whole 30-minute analysis for all symbols.

### 5.2 Feed the AI live context
- Schedule `retail_client` and `ff_client` ingestion in Celery beat.
- Change `SentimentAnalyzer` so live mode uses live scrapers when DB tables are stale/empty.

### 5.3 Make exits profitable
- Schedule `evaluate_exits` every 60 seconds.
- Enable `sl_ladder_enabled`, `partial_profit_enabled`, and `profit_lock_enabled`.
- Set `exit_reeval_enabled` to `true` once exits are validated for a few trades.

### 5.4 Close the learning loop
- Schedule `train_multitimeframe_and_team` nightly.
- Enable `model_perf_weighting_enabled` so `AnalystWeightOptimizer` updates per-model weights.
- Fix Qdrant as a hard dependency before the live signal loop is restored, then wire `_memory_guard` to use real outcomes.
- Add a `TradeOutcomeReview` task that writes **why** a trade won or lost (MFE/MAE, exit quality, session, regime) into `TradePattern` for the meta-models.

### 5.5 Calibrate risk
- Current `max_consecutive_losses` is 999 and `max_weekly_loss_pct` is 300%. These are effectively disabled.
- Set realistic circuit breakers: 3 consecutive losses = 30 min cooling, 5 = halt, weekly loss 6%, daily 3%.
- Fix position-size capping so the 0.01 micro-lot floor and 20% equity cap are respected without producing 0-size trades.

### 5.6 Measure, don't hope
- The first post-fix phase should be a **paper forward run with a fixed number of trades** (e.g., 50) and hard stop conditions, not open-ended live trading.

---

## 6. Implementation Roadmap

### Phase 0 — Pre-Flight (1-2 hours, no deploy)
1. Confirm the 7 captured decisions in Section 4.
2. Snapshot the DB and current settings before any changes.
3. Identify the Qdrant container/service and verify `QDRANT_URL` is reachable from the backend container. If it is down, restart/recreate it.
4. Ensure the `market_state_snapshots` Qdrant collection exists at 128 dimensions (recreate if needed).
5. Choose data provider: MT5 RPyC fix vs. MT5 ZMQ vs. MetaAPI.

### Phase 1 — Stop the Crash (1 day)
- [ ] Fix `mt5/mt5_service.py:111`: `if not rates or len(rates) == 0` → `if rates is None or len(rates) == 0`.
- [ ] Rebuild/restart `deez-forex-mt5` container.
- [ ] Add defensive handling in `backend/app/services/data/mt5_rpyc_client.py` to catch `ValueError` and return `[]`.
- [ ] Ensure `AnalysisAggregator` does not crash the entire analysis if one symbol's candles fail.
- [ ] Add a health check in `run_full_analysis` that logs a clear "HOLD reason" when data is unavailable instead of raising.
- [ ] Confirm Qdrant is healthy and `_memory_guard` can retrieve similar setups with outcomes. Do not proceed to Phase 2 until this passes.

**Acceptance:**
- `docker logs deez-forex-celery` shows `run_full_analysis` completing without `ValueError` for 3 consecutive runs.
- `/api/v1/ai/decisions` shows new `HOLD/BUY/SELL` decisions within 90 minutes of the fix.
- Qdrant collection `market_state_snapshots` is reachable from the backend and accepts 128-dim vectors.

### Phase 2 — Live Data & Sentiment (1 day)
- [ ] Schedule `ingest_retail_sentiment` and `ingest_forex_factory_calendar` in `backend/app/celery_app.py` beat (e.g., every 30 min and hourly).
- [ ] Modify `backend/app/analysis/sentiment.py` to fall back to live `_fetch_retail_sentiment` and `_analyze_news_sentiment` when DB tables are empty.
- [ ] Verify `news_headlines` and `retail_sentiment` tables receive rows.
- [ ] Confirm `refresh_sentiment_cache` task populates Redis cache.

**Acceptance:**
- New `ai_decisions` show non-zero sentiment scores.
- No more `sentiment_score: -0.05` with `news: {source: "none"}` for all symbols.

### Phase 3 — Exit Engine (1 day)
- [ ] Add `evaluate_exits` to `celery_app.py` beat_schedule (every 60 s).
- [ ] Set `exit_rules_enabled: true`, `sl_ladder_enabled: true`, `partial_profit_enabled: true`, `profit_lock_enabled: true`.
- [ ] Set `exit_reeval_enabled: true` after 24 hours of paper observation.
- [ ] Fix `ExitEvaluator` technical-flip rule to use the 1h `tech_snapshot` Redis key; remove hard-coded `redis://redis:6379/0` URL.

**Acceptance:**
- `docker logs deez-forex-celery` shows `evaluate_exits` running every minute and producing partial closes / SL moves on test trades.
- At least one trade takes a partial profit or moves SL to breakeven within 48 hours.

### Phase 4 — Learning Loop (2-3 days)
- [ ] Schedule `train_multitimeframe_and_team` nightly (or weekly if API cost is a concern).
- [ ] Enable `model_perf_weighting_enabled` and fix `refresh_model_performance` to update `AnalystWeightOptimizer` cache.
- [ ] Add `compute_trade_pattern` Celery task that runs on every close and writes a `TradePattern` row with `mfe_mae_ratio`, `r_multiple`, `exit_quality_score`, `optimal_hold_min`.
- [ ] Wire `update_outcome` to Qdrant once Qdrant is healthy; otherwise log and continue.
- [ ] Add a `trade_review` task that writes `TradeDecisionEvent` rows for ENTRY and CLOSE reasons.

**Acceptance:**
- `ModelPerformance` table has rows per model per window.
- `AnalystWeightOptimizer.get_cached_weights()` returns different weights after 5+ trades.
- `train_multitimeframe_and_team` completes at least one run and logs `test_auc`.

### Phase 5 — Risk & Sizing Calibration (1 day)
- [ ] Set `max_consecutive_losses` to 5.
- [ ] Set `max_weekly_loss_pct` to 6.0.
- [ ] Fix `RiskManager.calculate_position_size` so it does not return 0.0 for non-JPY pairs due to the 20% equity cap.
- [ ] Add a $140 hard-equity floor check before any new trade.
- [ ] Add `trade_aggressiveness` logic: reduce `ai_confidence_threshold` and `position_size` after 3 consecutive losses.

**Acceptance:**
- Unit tests for `calculate_position_size` pass for EURUSD, USDJPY, and XAUUSD.
- A run of 3 consecutive simulated losses triggers a cooling-off period.

### Phase 6 — Controlled Paper Forward Validation (1 week)
- [ ] Run the system in paper mode with a hard stop at 50 trades or -$10, whichever comes first.
- [ ] Log every `ai_decision` with `decision`, `confidence`, `model_used`, `analyst_opinions`, `regime`, `session`, and `qdrant_point_id`.
- [ ] At end of week, compute: win rate, profit factor, expectancy, average R-multiple, max drawdown, exit quality score.
- [ ] Compare to the post-reset baseline (35.9% WR, PF 0.3, Exp -$0.29).

**Acceptance:**
- System executes at least 10 trades.
- Win rate >= 45%, profit factor >= 1.0, expectancy >= 0.0.
- No single trade loses more than 1% of equity.

### Phase 7 — Optimization / Scale (after validation)
- [ ] If Phase 6 is positive: tighten `ai_confidence_threshold`, enable Qdrant RAG, allow live mode on $200 account.
- [ ] If Phase 6 is flat/negative: freeze entries, retrain on the new 50-trade data set, adjust `EntryQualityModel` threshold, and repeat Phase 6.

---

## 7. Definition of Done for This Plan

1. Trades are being opened and closed in paper mode.
2. The system records `TradePattern` and `ModelPerformance` for every closed trade.
3. `train_multitimeframe_and_team` runs automatically and improves `test_auc` over the baseline.
4. Exits use profit-lock, partial close, and breakeven rules, not just SL/TP.
5. A 1-week paper forward run meets the Phase 6 KPIs or triggers a documented pivot.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Free OpenRouter model quality is too low | Use `model_suite` = `production` with paid fallback and a daily API budget cap. |
| MT5 data feed continues to be flaky | Make `MetaApiClient` the primary and MT5 a fallback. |
| Too few trades to retrain | Use pre-reset AI-decision trades as initial labels; later blend with post-reset data. |
| Over-fitting to small sample | Use time-based walk-forward validation, not simple accuracy; don't optimize on 50 trades. |
| Qdrant unavailable | Block the live signal loop until Qdrant is fixed. Hard dependency approved in Decision 6. |
| Curve-fitting the exit rules | Alert-only mode for 24 h; compare rule exits vs. mechanical SL/TP. |

---

## 9. Final Approval Request

The plan has been updated with your 7 captured decisions, the web-research appendix, and the Qdrant hard-dependency gating.

1. Confirm the updated file path `docs/REVIVAL_AND_LEARNING_PLAN.md` is acceptable.
2. Give the green light to start **Phase 0** (Qdrant health check) and **Phase 1** (MT5 RPyC crash fix + account reset to $200).
3. I will not touch live trading, reset `equity_balance`, or run `docker compose build` until you explicitly approve.

---

## 10. Appendix — Web Research: Best Practices for AI/ML Trading & Learning

This section synthesizes recent research and practitioner best-practices that directly apply to the gaps in the current system.

### 10.1 Feature engineering matters more than model choice
- 80% of edge comes from features, not from picking the trendiest LLM or transformer (Obside, ForexExperts).
- Required inputs for a production FX AI:
  - Multi-timeframe OHLCV (1m, 5m, 15m, 1h, 4h, 1d)
  - Session tags (Asia, London, NY, overlap)
  - Volatility features (realized vol, Parkinson/Garman-Klass, ATR, vol-of-vol)
  - Macro / cross-asset (DXY, US yields, oil for CAD, gold for AUD/CHF, VIX)
  - Microstructure (spread, tick imbalance, VWAP distance) where available
  - Sentiment (retail positioning, COT, news, economic surprise vs consensus)
- **Rule:** every feature must be point-in-time; no global z-score normalization on the full sample; look-ahead bias is the silent killer.

### 10.2 Multi-agent / ensemble systems
- Market-Dependent Communication in Multi-Agent Alpha Generation (arXiv 2511.13614) shows that LLM agents improve when they share rankings and top-performing expressions.
- AlphaCrafter (arXiv 2605.05580) uses three specialized agents — Miner, Screener, Trader — with regime-conditioned factor ensembles. Key takeaway: factor selection should adapt to the current regime, not be static.
- Online ensemble learning (arXiv 2304.09947) dynamically reweights base models by recent out-of-sample `R^2`. The Weak Aggregating Algorithm (WAA) updates expert weights from realized performance and works well for FX hedging.
- **Application:** replace the static `AnalystWeightOptimizer` with an online WAA/EWA update on a 30- or 60-trade rolling window. Drop or discount models that decay.

### 10.3 Exit management: rules first, reinforcement learning second
- Deep reinforcement learning for stop-loss / target-gain exits can beat static SL/TP, but the reward function must be robust to noise (Neuravest, Lucena Research).
- Pro Trader RL (Expert Systems with Applications, 2025) splits trading into Buy, Sell, and Stop-Loss knowledge modules, each learned separately, then combined. This is a practical way to avoid a single over-simplified reward function.
- An Empirical Study of a Dynamic Stop-Loss Strategy with DRL on NASDAQ found positive impact on new data when the closing rules are actively managed.
- **Application:** keep the existing `ExitEvaluator` rule layer, but add a lightweight supervised "exit score" model (XGBoost or logistic) trained on MFE/MAE/time-in-trade → probability that closing now is optimal. Use it as a soft override above 0.70.

### 10.4 Position sizing and risk of ruin
- Kelly Criterion (`f* = (bp - q) / b`) maximizes geometric growth but full Kelly is unstable with estimation error.
- Professional practice: **Fractional Kelly (1/4 to 1/2 Kelly)**. This retains most growth while cutting drawdowns.
- You need 50-100+ clean trades to estimate `p` and `b` reliably. Until then, fixed fractional (1% per trade) is safer.
- Sizing does not create an edge; it preserves capital so the edge can compound.
- **Application:** implement a fractional-Kelly module that uses the last 50 closed trades by the current model. Cap at 1% until the model has a stable 50+ trade track record.

### 10.5 Validation: backtest is necessary, not sufficient
- Walk-forward validation exposes parameter drift and regime sensitivity, but it is not enough by itself; the analyst still runs many hidden trials (TrustedQuant).
- Combinatorial Purged Cross-Validation (CPCV) outperforms simple walk-forward for controlling probability of backtest overfitting (PBO) (SSRN 4686376).
- Walk-forward is what you do *before* paper trading to avoid wasting time; paper trading is what proves it works (AI Fin Hub).
- **Application:** keep backtest as validation-only per `AGENTS.md`; use walk-forward / CPCV to select the XGB entry-gate threshold; validate with a 1-week live paper forward run.

### 10.6 Learning from wins and losses
- Alpha Journal (Jeremy Knox) treats every live trade as training data and every post-mortem as a calibration event.
- Deterministic attribution: tag each closed trade to the dominant factor that cleared its gate, then accumulate win/loss rates per factor across a rolling window. This avoids "narrative overfitting" where LLMs explain results after the fact.
- Trade journal analyzers auto-tag trades by symbol, session, day-of-week, R:R, holding time, and emotional/revenge patterns (GitHub trade-journal-analyzer; StockAlpha).
- SHAP-based `TradeShapAnalyzer` (ML4T) can cluster failed trades by feature similarity and propose actionable fixes.
- **Application:**
  - On every close, write a `TradePattern` row with deterministic tags (regime, session, model, R-multiple, exit quality).
  - Maintain a `factor_winrate` table (or Redis cache) keyed by `symbol × session × regime × model`.
  - Use the 50 most recent patterns to update the `EntryQualityModel` and `TeamMetaModel` nightly.

### 10.7 Regime detection and adaptive models
- HMM-SVM/MKL hybrid models classify intraday regimes well and improve direction prediction (Springer 2025).
- Directional Change (DC) with Bayesian optimization of thresholds plus HMM regime detection outperforms fixed DC thresholds in FX (Physica A 2023).
- Regime-adaptive gradient ensembles (RAGe-ENS) for EURUSD achieved Sharpe 2.91 at the 4-hour horizon by weighting Transformer and XGB forecasts per regime.
- **Application:** keep the existing `RegimeDetector` but use its output to:
  - Switch `strategy_mode` (scalping vs. day-trading vs. swing)
  - Load regime-specific `AnalystWeightOptimizer` weights
  - Gate entry if `regime_confidence` is low

### 10.8 Confidence calibration
- Market forecasters are systematically overconfident (Journal of Behavioral Decision Making, 2013). Well-calibrated probabilities beat overconfident ones.
- A calibrated system should have a reliability curve: trades with predicted confidence 0.6 should win ~60% of the time.
- **Application:** after 50 closed trades, build a calibration table per `confidence` bucket. If `ai_confidence_threshold = 0.4` but 0.4-confidence trades only win 25%, raise the threshold to the confidence level that historically hits the target win rate (e.g., 0.55).

### 10.9 What to avoid
- Do not treat the LLM as a crystal ball. Its job is to combine weak signals, not predict price.
- Do not overfit to the backtest. Parameter search must be tracked and penalized (PBO, deflated Sharpe).
- Do not size with full Kelly until the system has 100+ live trades.
- Do not let one bad data provider kill the entire analysis for all symbols.
- Do not use backtest to train the meta-classifier for live trading (per `AGENTS.md`); use backtest only for validation and feature selection.

---

*Generated by Devin after codebase investigation and web research on 2026-08-19.*


## Backtest Validation Tool (NOT for Meta-Classifier Training)

**Status:** The standalone backtest is now a **technical validation tool only**.
It is NOT suitable for training a meta-classifier because the AI team requires
live real-time data (news sentiment, retail positioning, economic calendar) to
generate tradeable signals. With only stale pre-session candles + historical
macro/COT, the AI correctly returns HOLD at near-zero confidence.

### Key Findings (2026-06-27)

| Mode | Trades | Win Rate | P&L | Conclusion |
|------|--------|----------|-----|------------|
| Technical-only baseline | 217 | 27.2% | -$261 | Raw technical signal has **negative edge** |
| Full AI (stale data) | 0 | N/A | $0 | AI correctly uncertain without live context |

**Decision:** Use backtest only for:
- Verifying indicator calculations on historical candles
- Checking data pipeline integrity (macro, COT flows correctly)
- Sanity-checking execution simulation (spreads, SL/TP, ATR sizing)

**Do NOT use for:** Meta-classifier training, profitability backtesting, or
strategy optimization. Those require live forward data.

### Running the Validation Backtest

```bash
# Full AI mode (stale data only — expect 100% HOLD)
docker compose exec backend python /app/run_backtest_standalone.py

# Technical-only baseline (no LLM calls — fast, for indicator validation)
docker compose exec backend bash -c "BACKTEST_TECHNICAL_ONLY=true python3 /app/run_backtest_standalone.py"
```

### Data Ingested for Backtest

| Source | Rows | Date Range |
|--------|------|------------|
| FRED macro_series | 2,402 | Jun 2025 – Jun 2026 |
| CFTC COT reports | 734 | 2025 + 2026 |

### Files Modified

- `backend/run_backtest_standalone.py` — engine fixes, validation modes
- `backend/app/analysis/macro.py` — `as_of` param for historical queries
- `backend/app/analysis/sentiment.py` — `as_of` param for COT queries
- `backend/app/analysis/fundamental.py` — `as_of` param, DB calendar query
- `backend/app/services/data/fred_client.py` — added missing series IDs
- `backend/app/services/data/cot_client.py` — fixed date format, DB constraint
- `backend/app/tasks/backtest_full.py` — same engine fixes

### Implementation Plan

See `docs/backtest_data_and_engine_plan.md` for the full plan.

---

## Live Forward Trading (Production)

The AI team is designed for **live real-time data**:
- Live economic calendar (ForexFactory API)
- Live retail sentiment (Myfxbook scrape)
- Live news headlines (NewsAPI)
- Real-time macro (FRED daily updates)
- Real-time execution (MT5 ZMQ)

**The backtest cannot replicate this.** Evaluate the system in live paper mode.

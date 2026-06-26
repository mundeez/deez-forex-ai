# Backtest Realism Fix Plan

**Date:** 2026-06-26  
**Status:** Pending implementation  
**Affects:** `backend/run_backtest_standalone.py`, `backend/app/tasks/backtest_full.py`

---

## Why the current results are invalid

The current backtest produced +588% return on $200 starting equity across 140/988 sessions. This figure is not realistic. The dominant driver is a **look-ahead bias** that gives the AI decision-making access to candles that haven't happened yet at the point of entry.

### Root cause map

```
run_session()
 ├─ _load_candles(session_start → session_end)     ← loads FUTURE candles
 ├─ _run_technical(future_candles)                 ← LOOK-AHEAD #1
 ├─ _run_v2_decision(future_candles)               ← LOOK-AHEAD #2 (fed to AI)
 │    └─ TechnicalAnalyzer(future_candles)         ← LOOK-AHEAD #3
 └─ _simulate_trade(future_candles)
      ├─ entry = candles.iloc[0].open              ← correct
      ├─ _compute_atr_based_sl(future_candles)     ← LOOK-AHEAD #4
      └─ exit = candles.iloc[-1].close (session_end) ← LOOK-AHEAD #5
```

### Evidence

| Exit type     | Count | Win rate | PnL share |
|---------------|-------|----------|-----------|
| session_end   | 167   | **93%**  | 72%       |
| take_profit   | 56    | 100%     | 57%       |
| stop_loss     | 141   | 0%       | -29%      |

A 93% win rate on open-ended session exits is impossible in live trading. Random walk gives ~50%. The inflated rate exists because the AI's indicators already incorporated the session close price before the entry decision was made.

---

## Information barrier that must be enforced

```
Timeline per session:

 [session_start - 12h] ─────── [session_start] ──── [session_end]
          ↑                           ↑                    ↑
   context window begins          entry open           session close
   AI + indicators use            (iloc[0].open)     (walk-forward only)
   ONLY data before this line
```

**The AI and all indicator computation must never see any candle with `timestamp >= session_start`.**

---

## Change 1 — Strict context / execution split (CRITICAL)

**Files:** both  
**Priority:** must-fix

### What changes

Replace the single candle window with two separate, non-overlapping windows:

| Window | Time range | Used for |
|--------|-----------|----------|
| `ctx_5m` | `session_start - 4h → session_start` | AI decision + technical signal + ATR SL |
| `ctx_15m` | `session_start - 12h → session_start` | AI multi-timeframe context |
| `exec_5m` | `session_start → session_end` | Walk-forward simulation only |

### New helper method — `_load_context()`

Add to both files, replacing the existing `_load_candles` / `_load_candles_tf` calls inside `run_session`:

```python
async def _load_context(
    self, db, symbol: str, session_start: datetime,
    lookback: timedelta, timeframe: str
) -> pd.DataFrame:
    """Load candles strictly BEFORE session_start. Never bleeds into the session."""
    stmt = text("""
        SELECT timestamp, open, high, low, close, volume
        FROM historical_candles
        WHERE symbol = :symbol AND timeframe = :timeframe
          AND timestamp >= :start
          AND timestamp < :session_start        -- hard upper bound
        ORDER BY timestamp DESC
        LIMIT 100
    """)
    result = await db.execute(stmt, {
        "symbol": symbol,
        "timeframe": timeframe,
        "start": session_start - lookback,
        "session_start": session_start,
    })
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume"])
    return df.sort_values("timestamp").reset_index(drop=True)
```

### Changes to `run_session()`

**Before (both files):**
```python
candles_5m  = await self._load_candles(db, symbol, s_start, s_end)
candles_15m = await self._load_candles_tf(db, symbol, s_start, s_end, "15m")
tech        = self._run_technical(symbol, candles_5m)        # look-ahead
result      = await self._run_v2_decision(symbol, mode, candles_5m, candles_15m)  # look-ahead
trade       = self._simulate_trade(symbol, result, candles_5m, tech_signal=tech)
```

**After (both files):**
```python
# Context window — AI may see only this
ctx_5m  = await self._load_context(db, symbol, s_start, timedelta(hours=4),  "5m")
ctx_15m = await self._load_context(db, symbol, s_start, timedelta(hours=12), "15m")

# Execution window — simulator only, AI never sees this
exec_5m = await self._load_execution(db, symbol, s_start, s_end)

tech   = self._run_technical(symbol, ctx_5m)                     # pre-session only
result = await self._run_v2_decision(symbol, mode, ctx_5m, ctx_15m)  # pre-session only
trade  = self._simulate_trade(symbol, result, exec_5m, ctx_5m)   # exec for walk-forward,
                                                                  # ctx for ATR SL
```

### Changes to `_simulate_trade()`

Split the two candle uses explicitly:

```python
def _simulate_trade(
    self, symbol, decision, exec_candles, ctx_candles=None, tech_signal=None
):
    ...
    entry_price = float(exec_candles.iloc[0]["open"])  # unchanged

    # ATR SL: use pre-session context, not session candles
    atr_sl = self._compute_atr_based_sl(
        ctx_candles if ctx_candles is not None else exec_candles,
        entry_price, direction
    )

    # Walk-forward: iterate exec_candles only
    for idx in range(1, len(exec_candles)):
        candle = exec_candles.iloc[idx]
        ...
```

### `_run_v2_decision()` rename for clarity

Rename params from `candles_5m` / `candles_15m` to `ctx_5m` / `ctx_15m` to make the contract explicit and prevent future confusion.

---

## Change 2 — Spread and slippage simulation

**Files:** both  
**Priority:** must-fix

### Spread constants

Add at the top of both files:

```python
# Typical retail spreads in pips (conservative estimates)
SPREADS_PIPS = {
    "EURUSD": 1.5,
    "GBPUSD": 1.5,
    "USDJPY": 1.5,
    "AUDUSD": 1.5,
    "NZDUSD": 2.0,
    "USDCAD": 2.0,
    "USDCHF": 2.0,
    "EURGBP": 2.0,
    "GBPJPY": 4.0,
}
```

### Apply in `_simulate_trade()`

After computing `lot_size`, before returning:

```python
spread_pips = SPREADS_PIPS.get(symbol, 2.0)
spread_cost_usd = spread_pips * lot_size * 10.0
pnl_usd -= spread_cost_usd  # charged on every trade regardless of outcome
```

Add `"spread_cost_usd": spread_cost_usd` to the returned trade dict for transparency.

**Estimated impact:** ~$1.50–4.00 cost per trade. Over 200+ trades this is material (~$600–800 drag on a $200 account).

---

## Change 3 — Remove technical fallback

**Files:** `run_backtest_standalone.py`  
**Priority:** should-fix

The `_simulate_trade` function currently has a secondary path: if the AI team says HOLD but the technical signal is bullish/bearish with confidence ≥ 0.6, it overrides and trades anyway. This path:

- Inflates trade count beyond what the AI team alone produces
- Was originally added to improve trade frequency, but is not representative of live system behaviour

**Before:**
```python
if lead_decision in ("BUY", "SELL") and lead_conf >= 0.25:
    use_decision = decision
elif tech_signal and tech_signal.get("signal") in ("bullish", "bearish"):
    tech_conf = float(tech_signal.get("confidence", 0.5))
    if tech_conf >= 0.6:
        fallback = dict(decision)
        fallback["decision"] = "BUY" if tech_signal["signal"] == "bullish" else "SELL"
        ...
        use_decision = fallback
    else:
        return None
else:
    return None
```

**After:**
```python
if lead_decision not in ("BUY", "SELL") or lead_conf < 0.25:
    self.hold_reasons["low_confidence"] += 1
    return None
use_decision = decision
conf = lead_conf
```

Remove `tech_signal` parameter from `_simulate_trade()` and from the `run_session()` call site. Remove `_run_technical()` call from `run_session()` as it is no longer needed.

---

## Change 4 — Fix checkpoint resume equity drift

**Files:** `run_backtest_standalone.py`  
**Priority:** should-fix

### Problem

When the process is killed and restarted, the engine resumes from the saved `session_idx` and `equity`. However `loaded_trades` are read from the file but never used to reconcile `self.trade_count`. Separately, if the process ran a few sessions before the first checkpoint save, those sessions get re-processed on resume and their trades are appended a second time to the `.jsonl` file.

### Fixes

**A. Reconcile trade_count on resume:**

```python
# In run() after loading state
loaded_trades = self.checkpoint.load_trades()
self.trade_count = len(loaded_trades)   # authoritative count from file
```

**B. Track processed sessions to prevent double-append:**

Add to `CheckpointManager`:

```python
def session_key(self, symbol: str, session_start: datetime) -> str:
    return f"{symbol}_{session_start.isoformat()}"

def is_processed(self, key: str) -> bool:
    return key in self._processed_keys

def mark_processed(self, key: str):
    self._processed_keys.add(key)
```

Persist `_processed_keys` as a list inside the state JSON file. On resume, restore the set from state.

In `run_session()`:
```python
key = self.checkpoint.session_key(symbol, s_start)
if self.checkpoint.is_processed(key):
    return None   # skip — already done in a prior run
...
# after trade is recorded:
self.checkpoint.mark_processed(key)
```

---

## Change 5 — Pass correct session name to analysis snapshot

**Files:** both  
**Priority:** nice-to-have

The `analysis["session"]` field is hardcoded to `"london"` in both files regardless of which session is actually running. The `LeadStrategist` uses this field for session-aware analyst weighting.

In `run_session()`, the session name `s_name` is already available from the loop:

```python
# Before
analysis["session"] = "london"

# After
analysis["session"] = s_name   # "asian" / "london" / "london_ny" / "ny"
```

---

## Summary

| # | Change | Files | Category |
|---|--------|-------|----------|
| 1 | Strict context/execution split — no look-ahead | both | **must-fix** |
| 2 | Spread simulation on every trade | both | **must-fix** |
| 3 | Remove technical fallback override | standalone | should-fix |
| 4 | Checkpoint resume dedup + trade_count reconcile | standalone | should-fix |
| 5 | Correct session name in analysis snapshot | both | nice-to-have |

---

## Expected outcome after fixes

| Metric | Current (biased) | Expected (clean) |
|--------|-----------------|-----------------|
| Session_end win rate | 93% | ~50% |
| Overall win rate | ~57% | 40–55% |
| Profit factor | ~4.3 | 1.0–2.5 |
| Return (full 988 sessions) | +588% (invalid) | unknown — this is the actual test |

Any profit factor consistently above 1.5 across the full 988-session range (Oct 2025 → Jun 2026) on SL/TP exits alone would represent a genuine, testable edge worth pursuing in live paper trading.

---

## Files to modify

```
backend/
├── run_backtest_standalone.py       ← Changes 1, 2, 3, 4, 5
└── app/
    └── tasks/
        └── backtest_full.py         ← Changes 1, 2, 5
```

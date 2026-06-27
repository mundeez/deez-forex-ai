# Backtest Data Integrity & Engine Fix Plan

**Created:** 2026-06-27  
**Status:** Ready for implementation  
**Supersedes:** `backtest_realism_fix_plan.md` (look-ahead bias fixes already partially applied)  
**Affects:** `backend/run_backtest_standalone.py`, `backend/app/tasks/backtest_full.py`,  
`backend/app/analysis/macro.py`, `backend/app/analysis/sentiment.py`,  
`backend/app/analysis/fundamental.py`, `backend/app/services/data/fred_client.py`,  
`backend/app/services/data/cot_client.py`

---

## Q: Can we get real historical data for Oct 2025 – Jun 2026 from free sources?

**Yes — and the infrastructure is already mostly built.**

The codebase has three data clients and five DB tables for this exact purpose:

| What | Client file | DB table | Current state |
|---|---|---|---|
| Macro (VIX, DXY, yields, CPI, etc.) | `fred_client.py` | `macro_series` | Partial — some series missing Oct–Nov 2025 |
| Institutional positioning | `cot_client.py` | `cot_reports` | Table exists, **0 rows** |
| Economic calendar events | *(none yet)* | `economic_events` | Table exists, **0 rows** |
| Retail sentiment | *(none yet)* | `retail_sentiment` | Table exists, **0 rows** |
| News headlines | *(none yet)* | `news_headlines` | Table exists, **0 rows** |

**The problem is not missing code — the data has never been ingested.**

Additionally, there is a **fourth form of look-ahead bias** not covered in the previous plan:  
the analyzer methods `_latest_value()` (macro) and `_fetch_cot_from_db()` (sentiment) always  
return the most recent row in the DB — which in a June 2026 backtest run is a June 2026 value,  
not the October 2025 value the session needs. This must be fixed before real data is useful.

### Free data sources confirmed available for the backtest date range

| Source | What it provides | Availability | API method | Limit |
|---|---|---|---|---|
| **FRED API** | Macro series: VIX, DXY, yields, CPI, FEDFUNDS, UNRATE, ECB rate, HY spread | ✅ Full range | REST + `fredapi` package | 120 req/min free |
| **CFTC COT** | Weekly net positioning (long/short) for all 9 FX pairs + gold | ✅ Full range | Annual ZIP download (no key) | None |
| **ForexFactory** | Economic calendar events (NFP, CPI, FOMC, ECB, etc.) with impact + actual vs forecast | ✅ Oct 2025 – Mar 2026 via cached parquet; Apr–Jun via scraping | `forexfactory` Python package | None |
| **GDELT Project** | Global news sentiment scores per 15 min | ⚠️ Spotty Oct 2025–Feb 2026, strong from Mar 2026 | Raw file download | None |
| **AAII Sentiment** | Weekly investor sentiment (bullish/bearish/neutral) | ✅ Full range | Manual Excel download | None |

**Not usable free:** NewsAPI.org (1-month history limit on free tier), Investing.com (no free API, fragile scraping).

---

## Problem Summary

Before implementing anything, here is the full list of issues with the current backtest:

| # | Issue | Severity | Status |
|---|---|---|---|
| 1 | Look-ahead bias: AI saw session candles during decision | Critical | Fixed (partial run active) |
| 2 | `_latest_value()` uses today's macro, not session-date macro | Critical | **Not fixed** |
| 3 | `_fetch_cot_from_db()` uses most recent COT, not session-date COT | Critical | **Not fixed** |
| 4 | `cot_reports` table is empty — COT data never downloaded | High | **Not fixed** |
| 5 | `economic_events` table empty — fundamental analyst uses live calendar or mock | High | **Not fixed** |
| 6 | FRED series DXY/VIX/CRUDE/SP500/GOLD missing Oct–Nov 2025 | High | **Not fixed** |
| 7 | Weekend sessions generated (forex closed Sat/Sun) — 28% wasted AI calls | Medium | **Not fixed** |
| 8 | Context lookback only 4h = 48 candles — too few for indicators | Medium | **Not fixed** |
| 9 | No `ai_hold` counter — can't distinguish AI HOLD from data failure | Low | **Not fixed** |
| 10 | Backtest starts Oct 15 — first session has zero prior context data | Low | **Not fixed** |

---

## Implementation Plan

### Phase 1 — Fill the empty data tables  
*Prerequisite for everything else. No code changes to the backtest engine yet.*

#### 1A — Backfill FRED macro data (Oct 2025 gap)

**Problem:** The `macro_series` table has data from Dec 2025 for DXY, VIX, CRUDE, SP500, GOLD, and  
from Jun 2025 for DGS10, VIXCLS, ECBDFR, etc. The backtest starts Oct 15, 2025, meaning the  
first two months of sessions will see NULL for several macro indicators.

**Fix:** Call `FREDClient.ingest_all()` with `lookback_days=365` to force a backfill to Oct 2025  
for all series. Also add the missing series IDs (`DTWEXBGS` for DXY, `DCOILWTICO` for oil)  
that the `macro.py` analyzer queries but `fred_client.py` doesn't include.

**Steps:**

1. Edit `backend/app/services/data/fred_client.py` — add missing series to `FRED_SERIES` dict:

```python
FRED_SERIES = {
    # existing series …
    "DTWEXBGS":    "US Dollar Broad Index (DXY proxy)",
    "DCOILWTICO":  "WTI Crude Oil Price",
    "GOLDPMGBD228NLBM": "Gold Price PM Fix",
    "SP500":       "S&P 500 Index",
}
```

2. Run a one-off backfill task (can be done via docker exec):

```bash
docker compose exec backend python3 -c "
import asyncio
from app.services.data.fred_client import FREDClient
from app.database import get_celery_session

async def run():
    async with get_celery_session()() as db:
        client = FREDClient()
        totals = await client.ingest_all(db, lookback_days=365)
        print(totals)

asyncio.run(run())
"
```

**Expected output:** All `macro_series` series will have rows from Oct 2025 onward.

---

#### 1B — Download CFTC COT data (2025 + 2026)

**Problem:** `cot_reports` table has 0 rows. The `cot_client.py` exists and is correct.  
It only needs to be called.

**The CFTC URL format** (already in `cot_client.py`):
```
https://www.cftc.gov/files/dea/history/fut_fin_txt_2025.zip   ← TFF (FX)
https://www.cftc.gov/files/dea/history/fut_fin_txt_2026.zip   ← TFF (FX)
https://www.cftc.gov/files/dea/history/fut_disagg_txt_2025.zip ← Disagg (Gold)
https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip ← Disagg (Gold)
```

**Steps:**

1. Run a one-off ingestion for 2025 and 2026:

```bash
docker compose exec backend python3 -c "
import asyncio
from app.services.data.cot_client import COTClient
from app.database import get_celery_session

async def run():
    async with get_celery_session()() as db:
        client = COTClient()
        for year in [2025, 2026]:
            n = await client.ingest_year(db, year)
            print(f'{year}: {n} rows inserted')

asyncio.run(run())
"
```

**Expected output:** ~100 weekly rows per symbol per year across 10 symbols = ~2,000 rows total.

---

#### 1C — Ingest ForexFactory economic calendar

**Problem:** `economic_events` table empty. The `fundamental.py` analyzer falls back to mock  
data or calls a live URL (which returns this week's events, not historical ones).

**Solution:** Use the `forexfactory` PyPI package which ships a cached parquet file of all  
historical ForexFactory calendar events from 2010 through March 2026.

**Steps:**

1. Install the package inside the backend container (add to `requirements.txt`):

```
forexfactory==0.2.1
```

2. Create `backend/app/services/data/ff_client.py`:

```python
"""ForexFactory economic calendar ingestion.

Uses the `forexfactory` package's bundled parquet cache (covers ~2010–Mar 2026).
For Apr 2026+ events, falls back to the public JSON endpoint.
"""
import logging
from datetime import datetime, date
from typing import List, Dict, Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("app.services.data.ff")

CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}

async def ingest_calendar(db: AsyncSession, start: date, end: date) -> int:
    """Load ForexFactory events from package cache and insert into economic_events."""
    try:
        import forexfactory as ff
        df = ff.load_calendar()
    except ImportError:
        logger.error("forexfactory package not installed")
        return 0

    # Filter date range and relevant currencies
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    df = df[df["currency"].isin(CURRENCIES)]

    # Map impact labels
    impact_map = {"High": "high", "Medium": "medium", "Low": "low", "Non-Economic": "low"}
    df["impact"] = df["impact"].map(impact_map).fillna("low")

    stmt = text("""
        INSERT INTO economic_events
            (timestamp, currency, event_name, impact, actual, forecast, previous, source)
        VALUES
            (:timestamp, :currency, :event_name, :impact, :actual, :forecast, :previous, :source)
        ON CONFLICT DO NOTHING
    """)
    count = 0
    for _, row in df.iterrows():
        try:
            await db.execute(stmt, {
                "timestamp":  row["date"].to_pydatetime(),
                "currency":   row["currency"],
                "event_name": row.get("event", ""),
                "impact":     row["impact"],
                "actual":     str(row.get("actual", "")) or None,
                "forecast":   str(row.get("forecast", "")) or None,
                "previous":   str(row.get("previous", "")) or None,
                "source":     "forexfactory",
            })
            count += 1
        except Exception:
            pass
    await db.commit()
    return count
```

3. Run the ingestion:

```bash
docker compose exec backend python3 -c "
import asyncio
from datetime import date
from app.services.data.ff_client import ingest_calendar
from app.database import get_celery_session

async def run():
    async with get_celery_session()() as db:
        n = await ingest_calendar(db, date(2025, 10, 1), date(2026, 6, 19))
        print(f'Inserted {n} economic events')

asyncio.run(run())
"
```

**Expected:** ~500–1,500 high/medium-impact events for the backtest period.  
**Note:** ForexFactory package covers through March 2026. For Apr–Jun 2026, the live  
endpoint `https://nfs.faireconomy.media/ff_calendar_thisweek.json` can be called per-week  
during backtest (acceptable since those dates are in the past from today's perspective).

---

### Phase 2 — Fix look-ahead bias in analyzer queries

*This is the most important code change. Without it, real historical data still won't work correctly.*

#### 2A — Add `as_of_date` parameter to `MacroAnalyzer.analyze()`

**Problem:** `_latest_value()` always queries the most recent row. In backtest, "most recent" = today  
(Jun 2026), not the session date (e.g., Oct 2025). Using Jun 2026 macro data for an Oct 2025 session  
is look-ahead bias.

**File:** `backend/app/analysis/macro.py`

**Change `_latest_value()` → `_value_as_of()`:**

```python
async def _value_as_of(
    self, db: AsyncSession, series_id: str, as_of: datetime
) -> Optional[float]:
    """Fetch the most recent observation for series_id that existed on or before `as_of`."""
    try:
        result = await db.execute(
            select(models.MacroSeries)
            .where(models.MacroSeries.series_id == series_id)
            .where(models.MacroSeries.timestamp <= as_of)
            .order_by(models.MacroSeries.timestamp.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row.value if row else None
    except Exception:
        logger.warning("Failed to fetch macro series %s as_of %s", series_id, as_of, exc_info=True)
        return None
```

**Change `analyze()` signature:**

```python
async def analyze(self, db: AsyncSession = None, as_of: datetime = None) -> Dict[str, Any]:
    if as_of is None:
        as_of = datetime.utcnow()   # live mode: use latest
    # replace every _latest_value(db, x) call with _value_as_of(db, x, as_of)
```

---

#### 2B — Add `as_of_date` parameter to `SentimentAnalyzer.analyze()`

**Problem:** `_fetch_cot_from_db()` fetches the most recent COT report, not the one that  
existed on the session date.

**File:** `backend/app/analysis/sentiment.py`

**Change `_fetch_cot_from_db()` signature:**

```python
async def _fetch_cot_from_db(
    self, db: AsyncSession, symbol: str, as_of: datetime = None
) -> Dict[str, Any]:
    as_of = as_of or datetime.utcnow()
    ...
    result = await db.execute(
        select(models.COTReport)
        .where(models.COTReport.symbol == symbol)
        .where(models.COTReport.report_date <= as_of.date())   # ← add this filter
        .order_by(models.COTReport.report_date.desc())
        .limit(1)
    )
```

**Change `analyze()` signature:**

```python
async def analyze(
    self, symbol: str = "EURUSD", db: AsyncSession = None, as_of: datetime = None
) -> Dict[str, Any]:
    as_of = as_of or datetime.utcnow()
    ...
    cot = await self._fetch_cot_from_db(db, symbol, as_of) if db else self._fallback_cot()
```

---

#### 2C — Add `as_of_date` parameter to `FundamentalAnalyzer.analyze()`

**Problem:** `_fetch_economic_calendar()` either calls the live JSON endpoint (this week only)  
or returns mocks. For backtest, it must query `economic_events` from the DB filtered to  
`session_start - 24h → session_start + 24h`.

**File:** `backend/app/analysis/fundamental.py`

**New method `_fetch_calendar_from_db()`:**

```python
async def _fetch_calendar_from_db(
    self, db: AsyncSession, as_of: datetime, window_hours: int = 24
) -> List[Dict[str, Any]]:
    """Return events within window_hours before/after as_of from economic_events table."""
    from app import models
    from sqlalchemy import select
    from datetime import timedelta
    lo = as_of - timedelta(hours=window_hours)
    hi = as_of + timedelta(hours=window_hours)
    result = await db.execute(
        select(models.EconomicEvent)
        .where(models.EconomicEvent.timestamp >= lo)
        .where(models.EconomicEvent.timestamp <= hi)
        .order_by(models.EconomicEvent.timestamp)
    )
    rows = result.scalars().all()
    return [
        {
            "date": row.timestamp.isoformat(),
            "currency": row.currency,
            "event": row.event_name,
            "impact": row.impact,
            "actual": row.actual,
            "forecast": row.forecast,
            "previous": row.previous,
        }
        for row in rows
    ]
```

**Change `analyze()` signature:**

```python
async def analyze(
    self, symbol: str = "EURUSD", db: AsyncSession = None, as_of: datetime = None
) -> Dict[str, Any]:
    as_of = as_of or datetime.utcnow()
    if db is not None:
        events = await self._fetch_calendar_from_db(db, as_of)
    else:
        events = await self._fetch_economic_calendar()  # live fallback
    ...
```

---

### Phase 3 — Backtest engine fixes

#### 3A — Skip weekend sessions

**Problem:** The session generator yields sessions for Saturday and Sunday.  
Forex markets are closed. These burn API credits and count as no_candles.

**File:** `backend/run_backtest_standalone.py` (and `backtest_full.py`)

**Fix:** In the session-generation loop, add one line:

```python
for s_start, s_end, mode in self._generate_sessions(start_dt, end_dt):
    if s_start.weekday() >= 5:   # 5 = Saturday, 6 = Sunday
        continue
```

**Impact:** Removes ~28% of sessions immediately. Eliminates the `no_candles=180` problem  
observed in the HOLD breakdown logs.

---

#### 3B — Extend context lookback from 4h to 24h / 48h

**Problem:** 4 hours of 5m candles = 48 candles. RSI needs 14+ periods, MACD needs 26+,  
Bollinger Bands 20+. With only 48 candles, the indicators are operating at the very edge  
of their minimum warmup period, producing weak and noisy signals.

**File:** both backtest files

**Change in `run_session()`:**

```python
# Before
ctx_5m  = await self._load_context(db, symbol, s_start, timedelta(hours=4),  "5m")
ctx_15m = await self._load_context(db, symbol, s_start, timedelta(hours=12), "15m")

# After
ctx_5m  = await self._load_context(db, symbol, s_start, timedelta(hours=24), "5m")
ctx_15m = await self._load_context(db, symbol, s_start, timedelta(hours=48), "15m")
```

Also increase the SQL `LIMIT` in `_load_context()` from 100 to 300 to accommodate the larger window.

**Impact:** 24h of 5m data = ~288 candles. All indicators now have adequate warmup data.

---

#### 3C — Start backtest from Oct 17, 2025 (not Oct 15)

**Problem:** Sessions on Oct 15–16 have zero prior context because the historical candle  
data begins on Oct 15 at 20:20 UTC. Every session in the first 24h will hit `no_candles`.

**Fix:** Change `start_dt` in both files:

```python
# Before
start_dt = datetime(2025, 10, 15, tzinfo=timezone.utc)

# After
start_dt = datetime(2025, 10, 17, tzinfo=timezone.utc)  # ensures 24h of prior context
```

---

#### 3D — Pass `session_start` as `as_of` to all analyzers

**This is what connects Phase 2 changes to the backtest engine.**

**File:** `backend/run_backtest_standalone.py` and `backtest_full.py`

In `_run_v2_decision()` (or wherever `MacroAnalyzer`, `SentimentAnalyzer`,  
`FundamentalAnalyzer` are called), pass `as_of=session_start`:

```python
# Before (in _run_v2_decision or analysis snapshot builder):
macro_data      = await macro_analyzer.analyze(db=db)
sentiment_data  = await sentiment_analyzer.analyze(symbol=symbol, db=db)
fundamental_data = await fundamental_analyzer.analyze(symbol=symbol)

# After:
macro_data      = await macro_analyzer.analyze(db=db, as_of=session_start)
sentiment_data  = await sentiment_analyzer.analyze(symbol=symbol, db=db, as_of=session_start)
fundamental_data = await fundamental_analyzer.analyze(symbol=symbol, db=db, as_of=session_start)
```

---

#### 3E — Add `ai_hold` counter to `run_session()`

**Problem:** When the AI team returns "HOLD", there is no counter. The HOLD breakdown log  
shows `no_candles=X` but gives zero visibility into how many sessions had candles and the  
AI still said HOLD.

**File:** `backend/run_backtest_standalone.py`

In `__init__()`, add to `self.hold_reasons`:

```python
self.hold_reasons = {
    "no_candles": 0,
    "v2_failed": 0,
    "ai_hold": 0,       # ← new
    "low_confidence": 0,
    "zero_prices": 0,
}
```

In `run_session()`, after getting the AI decision:

```python
decision = v2_result.get("decision", "HOLD")
if decision not in ("BUY", "SELL"):
    self.hold_reasons["ai_hold"] += 1   # ← new
    return None
```

---

### Phase 4 — Optional improvements (lower priority)

#### 4A — GDELT news sentiment (spotty before Mar 2026)

GDELT publishes global news sentiment every 15 minutes at:
```
http://data.gdeltproject.org/gdeltv2/YYYYMMDDHHMMSS.export.CSV.zip
```

Coverage for Oct 2025 – Feb 2026 via the raw files is complete, but volume is enormous  
(~25k events per 15 min file). A practical approach:

1. Download daily aggregate files for the backtest period
2. Filter for keywords: `EURUSD`, `ECB`, `Federal Reserve`, `forex`, `dollar`, `euro`, `pound`
3. Average the Tone column per day per currency pair
4. Store in `news_headlines` table with a `tone_score` column
5. Use in `SentimentAnalyzer` as a third signal alongside COT and retail

This is worthwhile but not critical — COT data alone is the strongest forex sentiment signal.

---

#### 4B — Technical-only baseline experiment

Before re-running the full AI backtest, run a stripped version using only the  
`TechnicalAnalyzer` output (no LLM calls). This establishes a statistical baseline:

- If technical-only PF > 1.0: the technical signal has edge; the question becomes whether  
  the AI improves or degrades it
- If technical-only PF ≈ 1.0 or below: the system needs better alpha sources before the  
  AI team will find signal to trade on

This can be implemented by temporarily commenting out the LLM call in `_run_v2_decision()`  
and using the technical signal directly as the decision.

---

## Implementation order (recommended)

```
Day 1 (data ingestion — no engine changes):
  1A → Backfill FRED data          (~10 min to run)
  1B → Download CFTC COT data      (~5 min to run)
  1C → Ingest ForexFactory calendar (~15 min to run)

Day 2 (analyzer fixes):
  2A → MacroAnalyzer.analyze(as_of=)
  2B → SentimentAnalyzer.analyze(as_of=)
  2C → FundamentalAnalyzer.analyze(as_of=)

Day 3 (backtest engine):
  3A → Skip weekend sessions
  3B → Extend context to 24h/48h
  3C → Change start date to Oct 17
  3D → Wire as_of into run_session()
  3E → Add ai_hold counter

Day 4 (optional):
  4A → GDELT news sentiment
  4B → Technical-only baseline
```

---

## What to expect after implementation

| Metric | Current (look-ahead removed, stubs) | Expected after full fix |
|---|---|---|
| Trade rate | ~0.3% (1 trade per 333 sessions) | 3–8% (directional + real data signal) |
| Weekend sessions | 28% wasted | 0% |
| `no_candles` HOLD rate | 31% | <2% (only true data gaps) |
| Macro data accuracy | Today's values used for all sessions | Correct historical values per session date |
| COT positioning | Always fallback/null | Real weekly speculator net positions |
| Economic calendar | Mock or live-week-only | Real historical events with actual vs forecast |
| Win rate (expected) | Unknown (only 1 trade) | 45–55% (realistic; no edge from look-ahead) |

---

## Files to create/modify

| File | Action | Phase |
|---|---|---|
| `backend/app/services/data/fred_client.py` | Add missing series IDs | 1A |
| `backend/app/services/data/ff_client.py` | **Create new** | 1C |
| `backend/app/analysis/macro.py` | Add `as_of` param, replace `_latest_value` | 2A |
| `backend/app/analysis/sentiment.py` | Add `as_of` param to COT query | 2B |
| `backend/app/analysis/fundamental.py` | Add `as_of` param, DB calendar query | 2C |
| `backend/run_backtest_standalone.py` | Weekends, context window, start date, as_of wiring, counter | 3A–3E |
| `backend/app/tasks/backtest_full.py` | Same changes as standalone | 3A–3E |
| `backend/requirements.txt` | Add `forexfactory==0.2.1` | 1C |

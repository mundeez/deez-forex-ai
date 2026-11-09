"""Phase 7.2 sanity backtest: each registered variant over historical candles.

Purpose is NOT optimization — it is a bug-catcher: rule firing on the wrong
side, absurd frequency, controls that win. Any wildly-positive variant is a
look-ahead red flag (plan §7.2).

Costs: measured fills don't exist yet, so honest retail defaults are used
(~1.5-2 pips round-trip on majors, ~35 pips/point path on XAUUSD).
Simulation: signal on bar close -> enter next bar open; SL/TP resolved
intrabar, SL checked first (conservative); time-out at 12 bars.
"""
import asyncio, sys, logging
import asyncpg

sys.path.insert(0, "/app")
from app.strategies import generate_all, VARIANTS, VARIANT_PAIRS, pip_size

logging.basicConfig(level=logging.WARNING)
TF_SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
# honest round-trip cost per trade in pips (spread + slippage both sides)
COST_PIPS = {"EURUSD": 1.5, "GBPUSD": 1.7, "USDJPY": 1.6, "AUDUSD": 1.8,
             "USDCAD": 2.0, "USDCHF": 1.8, "XAUUSD": 35.0}
PIP_USD = {"EURUSD": 10.0, "GBPUSD": 10.0, "USDJPY": 9.1, "AUDUSD": 10.0,
           "USDCAD": 7.7, "USDCHF": 11.0, "XAUUSD": 1.0}


async def load_candles(db, symbol, tf):
    base_tf, mult = tf, 1
    if tf == "4h":
        base_tf, mult = "1h", 4
    elif tf == "1d":
        base_tf, mult = "1h", 24
    rows = await db.fetch(
        "SELECT timestamp, open, high, low, close FROM historical_candles "
        "WHERE symbol=$1 AND timeframe=$2 ORDER BY timestamp", symbol, base_tf)
    bars = [{"timestamp": r["timestamp"].timestamp()
             if hasattr(r["timestamp"], "timestamp") else float(r["timestamp"]),
             "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"])} for r in rows]
    if mult > 1:
        agg = {}
        span = 3600 * mult
        for b in bars:
            k = int(b["timestamp"] // span) * span
            g = agg.setdefault(k, {"timestamp": k, "open": b["open"],
                                   "high": b["high"], "low": b["low"], "close": b["close"]})
            g["high"] = max(g["high"], b["high"])
            g["low"] = min(g["low"], b["low"])
            g["close"] = b["close"]
        bars = [agg[k] for k in sorted(agg)]
    return bars


def simulate(bars, cands, tf, cost_pips, pip_usd, pip):
    out = []
    for idx, c in cands:
        if idx + 1 >= len(bars):
            continue
        entry = bars[idx + 1]["open"]
        cost = cost_pips * pip
        pnl = None
        for j in range(idx + 1, min(idx + 13, len(bars))):
            b = bars[j]
            if c.direction == "BUY":
                if b["low"] <= c.sl:   pnl = c.sl - entry - cost; break
                if b["high"] >= c.tp:  pnl = c.tp - entry - cost; break
            else:
                if b["high"] >= c.sl:  pnl = entry - c.sl - cost; break
                if b["low"] <= c.tp:   pnl = entry - c.tp - cost; break
        if pnl is None:
            e = bars[min(idx + 12, len(bars) - 1)]["close"]
            pnl = (e - entry if c.direction == "BUY" else entry - e) - cost
        out.append(pnl / pip * pip_usd)
    return out


async def main():
    db = await asyncpg.connect(
        "postgresql://forex:forex_secret@shared-postgres:5432/deez_forex")
    for vid, (gen, tfs) in VARIANTS.items():
        tf = tfs[0]
        all_trades = []
        for sym in VARIANT_PAIRS[vid]:
            need = {t: await load_candles(db, sym, t) for t in set(tfs)}
            bars = need.get(tf, [])
            # bound runtime: most recent ~25k bars (~8.5 months on 5m, ~2.8y on 1h)
            bars = bars[-5000:]
            for t in need:
                need[t] = need[t][-120000:]
            if len(bars) < 80:
                continue
            import bisect as _bis
            ts_by_tf = {t: [b["timestamp"] for b in need[t]] for t in need}
            cands = []
            for i in range(60, len(bars), 3):
                cb = {t: need[t][: _bis.bisect_right(ts_by_tf[t], bars[i]["timestamp"])][-500:]
                      for t in need}
                if any(len(cb[t]) < 30 for t in tfs):
                    continue
                try:
                    cands.extend((i, c) for c in gen(sym, cb, [], bars[i]["timestamp"]))
                except Exception:
                    pass
            pip = pip_size(sym)
            all_trades += simulate(bars, cands, tf,
                                   COST_PIPS.get(sym, 2.0), PIP_USD.get(sym, 10.0), pip)
        n = len(all_trades)
        wins = [t for t in all_trades if t > 0]
        denom = abs(sum(t for t in all_trades if t < 0))
        pf = round(sum(wins) / denom, 2) if denom else (99.0 if wins else 0.0)
        print(f"{vid:16s} trades={n:4d} WR={len(wins)/n*100 if n else 0:5.1f}% "
              f"net=${sum(all_trades):>9.0f} PF={pf}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

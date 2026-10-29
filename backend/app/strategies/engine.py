"""Deterministic strategy variants for the Phase 7 tournament.

Pre-registered variants (docs/STRATEGY_REBUILD_PLAN.md §3.1). Each
generate() is pure: same candles in -> same candidates out, so every arm
is exactly backtestable. ATR stops + fixed $5 risk keep expectancy
comparable across pairs and timeframes.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("app.strategies")

FX_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
GOLD_TREND_ONLY = {"TF-D1-DON20", "TF-H4-DON20"}

# (variant, pairs) — XAUUSD restricted to the two trend variants (§3.2)
VARIANT_PAIRS: Dict[str, List[str]] = {
    "TF-D1-DON20": FX_PAIRS + ["XAUUSD"],
    "TF-H4-DON20": FX_PAIRS + ["XAUUSD"],
    "TF-H1-DON55": FX_PAIRS,
    "SB-M15-LDN": FX_PAIRS,
    "SB-H1-NYO": FX_PAIRS,
    "ND-M15-DRIFT": FX_PAIRS,
    "MR-H1-BBFADE": FX_PAIRS,
    "LEGACY-M5-EMA": FX_PAIRS,
}

_TIMEFRAME_SEC = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


@dataclass
class Candidate:
    variant_id: str
    symbol: str
    direction: str            # BUY | SELL
    entry: float
    sl: float
    tp: float
    atr: float
    timeframe: str
    spread: float = 0.0       # price units at signal time
    regime: str = "unknown"
    rationale: str = ""


def instrument(symbol: str) -> Dict[str, float]:
    """Per-instrument economics — no EURUSD assumptions leak into gold (§3.2)."""
    if symbol == "XAUUSD":
        return {"pip": 0.10, "point_value_usd": 0.10}   # 1 pip = $0.10 move; 1 lot = $10/pip*100
    if symbol.endswith("JPY"):
        return {"pip": 0.01, "point_value_usd": 0.01}
    return {"pip": 0.0001, "point_value_usd": 0.0001}


def pip_size(symbol: str) -> float:
    return instrument(symbol)["pip"]


# ---------- indicator helpers (pure numpy-free math on candle dicts) ----------

def _closes(c): return [x["close"] for x in c]
def _highs(c):  return [x["high"] for x in c]
def _lows(c):   return [x["low"] for x in c]


def atr(candles: List[Dict], n: int = 14) -> Optional[float]:
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-n:]) / n


def ema(values: List[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def adx(candles: List[Dict], n: int = 14) -> Optional[float]:
    if len(candles) < 2 * n + 1:
        return None
    pdm, ndm, trs = [], [], []
    for i in range(1, len(candles)):
        up = candles[i]["high"] - candles[i - 1]["high"]
        dn = candles[i - 1]["low"] - candles[i]["low"]
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"] - candles[i - 1]["close"])))
    dx = []
    for j in range(n, len(trs)):
        atr_n = sum(trs[j - n:j]) or 1e-12
        pdi = 100 * sum(pdm[j - n:j]) / atr_n
        ndi = 100 * sum(ndm[j - n:j]) / atr_n
        dx.append(100 * abs(pdi - ndi) / max(pdi + ndi, 1e-12))
    return sum(dx[-n:]) / len(dx[-n:]) if dx else None


def rsi(values: List[float], n: int = 14) -> Optional[float]:
    if len(values) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    g = sum(gains[-n:]) / n; l = sum(losses[-n:]) / n
    if l == 0:
        return 100.0
    return 100 - 100 / (1 + g / l)


def donchian(candles: List[Dict], n: int, exclude_last: bool = True):
    w = candles[-(n + 1):-1] if exclude_last else candles[-n:]
    return (max(_highs(w)), min(_lows(w))) if len(w) >= n else (None, None)


def bollinger(values: List[float], n: int, sd: float):
    if len(values) < n:
        return None, None, None
    w = values[-n:]
    m = sum(w) / n
    var = sum((v - m) ** 2 for v in w) / n
    s = var ** 0.5
    return m + sd * s, m, m - sd * s


def regime_of(candles_d1: List[Dict]) -> str:
    """Deterministic regime: D1 ADX + EMA50 side. LLM regime classifier
    refines this in Phase 7.3; the gate just needs a sane default."""
    a = adx(candles_d1)
    if a is None:
        return "unknown"
    e = ema(_closes(candles_d1), 50)
    c = candles_d1[-1]["close"]
    if a >= 25:
        return "trending_up" if (e and c > e) else ("trending_down" if e and c < e else "volatile_news")
    if a >= 20:
        return "volatile_news"
    return "ranging"


def _session_of(ts: float) -> str:
    try:
        h = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    except (OverflowError, OSError, ValueError):
        return "offhours"  # corrupt/millisecond timestamp — don't kill the variant
    if 0 <= h < 7: return "asian"
    if 7 <= h < 13: return "london"
    if 13 <= h < 21: return "ny"
    return "offhours"


# ---------- generators ----------

def _trend_donchian(variant_id: str, tf: str, don_e: int, don_x: int,
                    adx_min: float, symbol: str, c: List[Dict],
                    d1_candles: Optional[List[Dict]] = None) -> List[Candidate]:
    a = atr(c); x = adx(c)
    if a is None or x is None or x < adx_min:
        return []
    close = c[-1]["close"]
    hi, lo = donchian(c, don_e)
    e50 = ema(_closes(c), 50)
    if hi is None or e50 is None:
        return []
    reg = regime_of(d1_candles) if d1_candles else regime_of(c)
    if variant_id == "TF-H1-DON55":
        # multi-TF: require D1 EMA50 agreement
        e_d1 = ema(_closes(d1_candles or []), 50)
        c_d1 = (d1_candles or [{}])[-1].get("close")
        if e_d1 is None or c_d1 is None:
            return []
        if not ((close > e50) == (c_d1 > e_d1)):
            return []
    out = []
    if close > hi and close > e50:
        out.append(Candidate(variant_id, symbol, "BUY", close,
                             close - 2 * a, close + 3 * a, a, tf, regime=reg,
                             rationale=f"Donchian({don_e}) break + ADX {x:.0f}>{adx_min:.0f} + above EMA50"))
    elif close < lo and close < e50:
        out.append(Candidate(variant_id, symbol, "SELL", close,
                             close + 2 * a, close - 3 * a, a, tf, regime=reg,
                             rationale=f"Donchian({don_e}) break + ADX {x:.0f}>{adx_min:.0f} + below EMA50"))
    return out


def _session_breakout(variant_id: str, tf: str, r0: int, r1: int, w1: int,
                      hard_exit: int, symbol: str, c: List[Dict],
                      c_d1: List[Dict], now: float) -> List[Candidate]:
    """Range breakout: today’s [r0:r1) UTC range broken by a CLOSED candle
    inside the entry window (range_end..window_end UTC)."""
    a_d1 = atr(c_d1) or 0.0
    a_tf = atr(c)
    if not a_d1 or a_tf is None:
        return []
    now_h = datetime.fromtimestamp(now, tz=timezone.utc).hour
    if not (r1 <= now_h < w1):
        return []
    day0 = datetime.fromtimestamp(now, tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    rng = [b for b in c if day0 + r0 * 3600 <= b["timestamp"] < day0 + r1 * 3600]
    win = [b for b in c if day0 + r1 * 3600 <= b["timestamp"] <= now]
    if len(rng) < 2 or not win:
        return []
    rh, rl = max(_highs(rng)), min(_lows(rng))
    rsize = rh - rl
    if not (0.5 * a_d1 <= rsize <= 1.5 * a_d1):
        return []
    last = win[-1]
    if last["close"] > rh:
        return [Candidate(variant_id, symbol, "BUY", last["close"], rl,
                          last["close"] + rsize, a_tf, tf,
                          regime=_session_of(now),
                          rationale=f"{variant_id} range {rsize/pip_size(symbol):.1f}p breakout BUY")]
    if last["close"] < rl:
        return [Candidate(variant_id, symbol, "SELL", last["close"], rh,
                          last["close"] - rsize, a_tf, tf,
                          regime=_session_of(now),
                          rationale=f"{variant_id} range {rsize/pip_size(symbol):.1f}p breakout SELL")]
    return []


def _news_drift(variant_id: str, symbol: str, c: List[Dict],
                events: List[Dict], now: float) -> List[Candidate]:
    """15 min after a high-impact release, enter in the direction of the
    first 15-min candle if it moved >= 1.0 x ATR(60)."""
    a = atr(c[-60:]) if len(c) >= 60 else atr(c)
    if a is None:
        return []
    out = []
    for ev in events or []:
        et = ev.get("time")
        try:
            ets = datetime.fromisoformat(str(et).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        delay = now - ets
        if not (15 * 60 <= delay <= 90 * 60):
            continue
        first = [b for b in c if ets <= b["timestamp"] < ets + 900]
        prev = [b for b in c if b["timestamp"] < ets]
        if not first or not prev:
            continue
        move = first[0]["close"] - prev[-1]["close"]
        if abs(move) < 1.0 * a:
            continue
        d = "BUY" if move > 0 else "SELL"
        sl = prev[-1]["close"]
        risk = abs(first[0]["close"] - sl) or a
        tp = first[0]["close"] + (1.5 * risk if d == "BUY" else -1.5 * risk)
        out.append(Candidate(variant_id, symbol, d, first[0]["close"], sl, tp,
                             a, "15m", regime="volatile_news",
                             rationale=f"post-news drift after '{ev.get('title','?')}' move {move/pip_size(symbol):.0f}p"))
    return out


def _mean_reversion(variant_id: str, symbol: str, c: List[Dict]) -> List[Candidate]:
    a = atr(c); x = adx(c); r = rsi(_closes(c))
    if a is None or x is None or r is None or x >= 20:
        return []
    up, mid, lo = bollinger(_closes(c), 20, 2.5)
    if up is None:
        return []
    close = c[-1]["close"]
    if close > up and r > 75:
        return [Candidate(variant_id, symbol, "SELL", close, close + 1.5 * a, mid,
                          a, "1h", regime="ranging",
                          rationale=f"BB(20,2.5) fade SELL RSI {r:.0f} ADX {x:.0f}")]
    if close < lo and r < 25:
        return [Candidate(variant_id, symbol, "BUY", close, close - 1.5 * a, mid,
                          a, "1h", regime="ranging",
                          rationale=f"BB(20,2.5) fade BUY RSI {r:.0f} ADX {x:.0f}")]
    return []


def _legacy_ema(variant_id: str, symbol: str, c: List[Dict]) -> List[Candidate]:
    """Control arm: the existing EMA9/21 + ADX>15 + RSI rule, ungated."""
    a = atr(c); x = adx(c); r = rsi(_closes(c))
    e9, e21 = ema(_closes(c), 9), ema(_closes(c), 21)
    if None in (a, x, r, e9, e21) or x < 15:
        return []
    close = c[-1]["close"]
    if e9 > e21 and r < 70:
        return [Candidate(variant_id, symbol, "BUY", close,
                          close - 1.5 * a, close + 2.5 * a, a, "5m",
                          regime=_session_of(c[-1]["timestamp"]),
                          rationale="LEGACY EMA9>21 + ADX>15 BUY (control)")]
    if e9 < e21 and r > 30:
        return [Candidate(variant_id, symbol, "SELL", close,
                          close + 1.5 * a, close - 2.5 * a, a, "5m",
                          regime=_session_of(c[-1]["timestamp"]),
                          rationale="LEGACY EMA9<21 + ADX>15 SELL (control)")]
    return []


# variant_id -> (generator, required timeframes)
VARIANTS: Dict[str, Any] = {
    "TF-D1-DON20":  (lambda s, cb, ev, now: _trend_donchian("TF-D1-DON20", "1d", 20, 10, 20, s, cb["1d"]), ["1d"]),
    "TF-H4-DON20":  (lambda s, cb, ev, now: _trend_donchian("TF-H4-DON20", "4h", 20, 10, 20, s, cb["4h"], cb.get("1d")), ["4h", "1d"]),
    "TF-H1-DON55":  (lambda s, cb, ev, now: _trend_donchian("TF-H1-DON55", "1h", 55, 20, 25, s, cb["1h"], cb.get("1d")), ["1h", "1d"]),
    "SB-M15-LDN":   (lambda s, cb, ev, now: _session_breakout("SB-M15-LDN", "15m", 0, 7, 10, 12, s, cb["15m"], cb["1d"], now), ["15m", "1d"]),
    "SB-H1-NYO":    (lambda s, cb, ev, now: _session_breakout("SB-H1-NYO", "1h", 7, 12, 15, 20, s, cb["1h"], cb["1d"], now), ["1h", "1d"]),
    "ND-M15-DRIFT": (lambda s, cb, ev, now: _news_drift("ND-M15-DRIFT", s, cb["15m"], ev, now), ["15m"]),
    "MR-H1-BBFADE": (lambda s, cb, ev, now: _mean_reversion("MR-H1-BBFADE", s, cb["1h"]), ["1h"]),
    "LEGACY-M5-EMA":(lambda s, cb, ev, now: _legacy_ema("LEGACY-M5-EMA", s, cb["5m"]), ["5m"]),
}


def generate_all(symbol: str, candles_by_tf: Dict[str, List[Dict]],
                 events: List[Dict], now: float) -> List[Candidate]:
    """Run every active variant registered for this symbol. Each generator
    is wrapped so one bad variant can't kill the cycle."""
    out = []
    for vid, (gen, tfs) in VARIANTS.items():
        if symbol not in VARIANT_PAIRS.get(vid, []):
            continue
        if any(tf not in candles_by_tf or len(candles_by_tf[tf]) < 30 for tf in tfs):
            continue
        try:
            out.extend(gen(symbol, candles_by_tf, events, now))
        except Exception as exc:
            logger.warning("variant %s on %s failed: %s", vid, symbol, exc)
    return out

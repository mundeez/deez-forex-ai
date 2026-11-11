"""LLM market-regime classifier (Phase 7.3.1).

Once per (symbol, session) the classifier reads a compact statistical summary
of recent candles and returns one of:
    trending_up | trending_down | ranging | volatile

The label gates which rule families may fire inside run_variant_engine:
  - TF-*   requires trending_* (direction must match)
  - MR-*   requires ranging
  - SB-*   exempt (session window is the regime)
  - ND-*   exempt (event-driven; 'volatile' is its habitat)

Results are cached in Redis per symbol+session so cost stays ~1 call/pair/
session (~18 calls/day per plan §5).
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REGIMES = ("trending_up", "trending_down", "ranging", "volatile")
MODEL = "qwen/qwen3-next-80b-a3b-instruct"
_TTL = 10 * 3600  # outlives any session


def _summarize(symbol: str, candles: List[Dict]) -> Dict[str, Any]:
    """Compact stats for the prompt — no raw candle dump."""
    from app.strategies.engine import atr, adx, ema, _closes
    closes = _closes(candles)
    if len(closes) < 50:
        return {}
    a = atr(candles) or 0.0
    x = adx(candles) or 0.0
    e50 = ema(closes, 50) or closes[-1]
    move_24 = closes[-1] - closes[-24]
    move_72 = closes[-1] - closes[-72] if len(closes) >= 72 else move_24
    rng = max(c["high"] for c in candles[-24:]) - min(c["low"] for c in candles[-24:])
    return {
        "last": closes[-1],
        "move_24h_pct": round(100 * move_24 / closes[-1], 3),
        "move_72h_pct": round(100 * move_72 / closes[-1], 3),
        "range_24h_atr": round(rng / a, 2) if a else None,
        "adx_14": round(x, 1),
        "price_vs_ema50_pct": round(100 * (closes[-1] - e50) / closes[-1], 3),
        "atr_pips": round(a / (0.01 if symbol.endswith("JPY") else (0.1 if symbol == "XAUUSD" else 0.0001)), 1),
    }


async def classify(symbol: str, candles_1h: List[Dict], session: str,
                   ai, redis, pool: List[str]) -> Optional[str]:
    """Return the LLM regime label for (symbol, session), or None on failure."""
    import json
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"variant:regime:{symbol}:{day}:{session}"
    try:
        cached = await redis.get(key)
        if cached:
            return json.loads(cached).get("regime")
    except Exception:
        pass

    stats = _summarize(symbol, candles_1h[-120:] if len(candles_1h) > 120 else candles_1h)
    if not stats:
        return None
    prompt = (
        f"Classify the CURRENT market regime for {symbol} from these 1h-candle stats: "
        f"{json.dumps(stats)}. "
        "Pick exactly one: trending_up, trending_down, ranging, volatile. "
        "Reply ONLY JSON: {\"regime\": \"<label>\", \"confidence\": 0-1, "
        "\"rationale\": \"<=100 chars\"}")
    chain = [MODEL] + [m for m in pool if m != MODEL]
    regime = None
    try:
        data, used = await ai._post_with_failover(
            ai._request_headers(),
            {"temperature": 0.1, "max_tokens": 256,
             "messages": [{"role": "user", "content": prompt}],
             "response_format": {"type": "json_object"}},
            chain, reasoning={"effort": "low"})
        parsed = ai._parse_object(data["choices"][0]["message"]["content"])
        regime = str(parsed.get("regime", "")).lower().strip()
        if regime not in REGIMES:
            regime = None
        else:
            logger.info("regime %s %s=%s (%s) via %s — %s",
                        symbol, session, regime,
                        parsed.get("confidence"), used,
                        str(parsed.get("rationale", ""))[:80])
    except Exception as exc:
        logger.warning("regime classify %s failed: %s", symbol, exc)
        return None

    try:
        await redis.set(key, json.dumps({"regime": regime}), ex=_TTL)
    except Exception:
        pass
    return regime

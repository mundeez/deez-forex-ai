"""Daily Bias — pre-market reasoning-model pass.

Runs once per symbol (or once globally) to digest overnight news/macro/
central-bank rhetoric into a cached directional bias. The fast intraday team
injects this bias at zero latency cost.

Recommended model: DeepSeek-R1 (free or paid) for chain-of-thought reasoning.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.utils.time import utc_now

import redis.asyncio as aioredis

from app.ai.openrouter_client import OpenRouterClient
from app.ai.model_router import ModelRouter
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.ai.team.daily_bias")


class DailyBiasEngine:
    """Generates and caches a daily directional bias per symbol."""

    _SYSTEM_PROMPT = (
        "You are a macro strategist performing a daily pre-market bias assessment. "
        "Digest overnight news, macroeconomic data, central bank rhetoric, and cross-asset "
        "correlations to produce a single directional bias per symbol. "
        "Output ONLY a JSON object with keys: bias (BULLISH|BEARISH|NEUTRAL), "
        "confidence (0.0-1.0), rationale (string), key_levels ([support, resistance]), "
        "risk_events (string list of today's high-impact events)."
    )

    def __init__(self, model: str = None):
        self.model = model or settings.MODEL_MACRO
        self.client = OpenRouterClient()

    async def compute(
        self,
        symbol: str,
        macro_snapshot: Dict[str, Any],
        news_summary: str = "",
        router: Optional[ModelRouter] = None,
    ) -> Dict[str, Any]:
        prompt = (
            f"Symbol: {symbol}\n"
            f"Date: {utc_now().strftime('%Y-%m-%d')}\n\n"
            f"Macro Snapshot:\n{json.dumps(macro_snapshot, indent=2)[:2000]}\n\n"
            f"Overnight News Summary:\n{news_summary[:1500]}\n\n"
            "Generate the daily bias."
        )
        payload = {
            "temperature": 0.2,
            "max_tokens": 384,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            data, used_model = await self.client._post_with_failover(
                self.client._request_headers(),
                payload,
                [self.model],
                router=router,
            )
            content = data["choices"][0]["message"]["content"]
            parsed = self.client._parse_object(content)
        except Exception as exc:
            logger.error("Daily bias computation failed for %s: %s", symbol, exc, exc_info=True)
            return {
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "rationale": f"Error: {str(exc)[:80]}",
                "key_levels": [],
                "risk_events": [],
                "model_used": self.model,
                "computed_at": utc_now().isoformat(),
            }

        return {
            "bias": str(parsed.get("bias", "NEUTRAL")).upper(),
            "confidence": float(parsed.get("confidence") or 0.0),
            "rationale": parsed.get("rationale", ""),
            "key_levels": parsed.get("key_levels", []),
            "risk_events": parsed.get("risk_events", []),
            "model_used": used_model,
            "computed_at": utc_now().isoformat(),
        }

    async def cache(self, symbol: str, bias: Dict[str, Any], ttl_sec: int = 28800) -> None:
        """Store the daily bias in Redis (default 8h TTL)."""
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.set(f"daily_bias:{symbol}", json.dumps(bias), ex=ttl_sec)
            await r.close()
        except Exception as exc:
            logger.warning("Failed to cache daily bias for %s: %s", symbol, exc)

    async def get_cached(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached daily bias."""
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            raw = await r.get(f"daily_bias:{symbol}")
            await r.close()
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Daily bias cache miss for %s: %s", symbol, exc)
        return None

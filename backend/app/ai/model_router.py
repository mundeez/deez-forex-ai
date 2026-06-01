"""Free-model round-robin router with rate-limit failover.

Distributes OpenRouter calls across a pool of free models using an atomic
Redis round-robin counter, skips models that are in cooldown (after a
rate-limit / quota error), and falls back to a paid model only when the
entire free pool is exhausted. This lets the platform keep trading on free
models without hitting per-model access limits.

State lives in Redis (already used for Celery + websocket pub/sub):
    ai:rr:index            INCR counter for round-robin position
    ai:cooldown:<model>    presence = model is cooling down (TTL = cooldown_sec)
"""
import logging
from typing import List, Optional

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger("app.ai.model_router")
settings = get_settings()

# Curated free models verified against the live OpenRouter catalogue.
# Ordered by general suitability for structured forex JSON decisions
# (strong reasoning + reliable JSON adherence first).
DEFAULT_FREE_POOL: List[str] = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "deepseek/deepseek-v4-flash:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-120b:free",
    "z-ai/glm-4.5-air:free",
    "deepseek/deepseek-r1:free",  # reasoning model for macro / verifier roles
]

# Cheap, very reliable JSON-mode model used only when every free model is
# cooling down (requires a funded OpenRouter key).
DEFAULT_PAID_FALLBACK = "google/gemini-2.5-flash"

_RR_KEY = "ai:rr:index"
_COOLDOWN_PREFIX = "ai:cooldown:"

# HTTP statuses that mean "this model is unavailable right now" -> cooldown + failover.
RATE_LIMIT_STATUSES = (402, 403, 429)
SERVER_ERROR_STATUSES = (500, 502, 503, 504)


def parse_pool(raw: Optional[str]) -> List[str]:
    """Parse a comma/newline separated model list into a clean ordered list."""
    if not raw:
        return list(DEFAULT_FREE_POOL)
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    pool = [p for p in parts if p]
    return pool or list(DEFAULT_FREE_POOL)


class ModelRouter:
    """Selects which model to call and tracks per-model cooldowns."""

    def __init__(
        self,
        free_pool: Optional[List[str]] = None,
        paid_fallback: Optional[str] = None,
        cooldown_sec: int = 120,
        rotation_enabled: bool = True,
    ):
        pool = [m.strip() for m in (free_pool or DEFAULT_FREE_POOL) if m and m.strip()]
        self.free_pool = pool or list(DEFAULT_FREE_POOL)
        self.paid_fallback = (paid_fallback or "").strip() or None
        self.cooldown_sec = max(int(cooldown_sec or 0), 0)
        self.rotation_enabled = rotation_enabled

    # -- Redis helpers --------------------------------------------------------
    async def _redis(self):
        return aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    @staticmethod
    def _cooldown_key(model: str) -> str:
        return f"{_COOLDOWN_PREFIX}{model}"

    async def mark_cooldown(self, model: str, seconds: Optional[int] = None) -> None:
        """Put a model on cooldown so it is skipped by subsequent rotations."""
        ttl = self.cooldown_sec if seconds is None else int(seconds)
        if not model or ttl <= 0:
            return
        try:
            r = await self._redis()
            await r.set(self._cooldown_key(model), "1", ex=ttl)
            await r.aclose()
        except Exception:
            logger.warning("Failed to set cooldown for %s", model, exc_info=True)

    async def _cooled_set(self, models: List[str]) -> set:
        if not models:
            return set()
        try:
            r = await self._redis()
            vals = await r.mget([self._cooldown_key(m) for m in models])
            await r.aclose()
            return {m for m, v in zip(models, vals) if v is not None}
        except Exception:
            logger.warning("Failed to read model cooldowns", exc_info=True)
            return set()

    async def _next_offset(self, n: int) -> int:
        if n <= 0:
            return 0
        try:
            r = await self._redis()
            idx = await r.incr(_RR_KEY)
            await r.aclose()
            return (int(idx) - 1) % n
        except Exception:
            logger.warning("Round-robin counter unavailable, starting at 0", exc_info=True)
            return 0

    # -- Public API -----------------------------------------------------------
    async def get_candidates(self, primary: Optional[str] = None) -> List[str]:
        """Return an ordered list of models to attempt for a single request.

        Rotation disabled: ``[primary]`` then the rest of the free pool then the
        paid fallback (so a forced model still has failover).

        Rotation enabled: start at the round-robin offset, prefer models that
        are not cooling down, append the paid fallback, and only retry
        cooled-down free models as an absolute last resort.
        """
        pool = list(self.free_pool)

        if not self.rotation_enabled:
            ordered = [primary] if primary else []
            ordered += [m for m in pool if m != primary]
            if self.paid_fallback and self.paid_fallback not in ordered:
                ordered.append(self.paid_fallback)
            return ordered

        n = len(pool)
        offset = await self._next_offset(n) if n else 0
        rotated = [pool[(offset + i) % n] for i in range(n)] if n else []
        cooled = await self._cooled_set(rotated)
        fresh = [m for m in rotated if m not in cooled]
        stale = [m for m in rotated if m in cooled]

        ordered = list(fresh)
        if self.paid_fallback and self.paid_fallback not in ordered:
            ordered.append(self.paid_fallback)
        ordered += stale  # last resort: try a cooling-down free model anyway
        return ordered

    async def status(self) -> dict:
        """Snapshot of rotation state for observability endpoints."""
        all_models = list(self.free_pool)
        if self.paid_fallback:
            all_models.append(self.paid_fallback)
        cooled = await self._cooled_set(all_models)
        return {
            "rotation_enabled": self.rotation_enabled,
            "free_pool": self.free_pool,
            "paid_fallback": self.paid_fallback,
            "cooldown_sec": self.cooldown_sec,
            "cooling_down": sorted(cooled),
            "available": [m for m in self.free_pool if m not in cooled],
        }

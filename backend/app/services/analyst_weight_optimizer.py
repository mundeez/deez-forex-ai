"""AnalystWeightOptimizer — regime/session-aware weight tuning.

Learns optimal weights for technical, fundamental, sentiment, and macro
analysts based on historical performance in each regime and session.

Weights are cached in Redis and injected into the LeadStrategist prompt.
"""
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger("app.services.analyst_weight_optimizer")

DEFAULT_WEIGHTS = {
    "technical": 0.40,
    "fundamental": 0.25,
    "sentiment": 0.20,
    "macro": 0.15,
}


class AnalystWeightOptimizer:
    """Optimize analyst weights per regime and session."""

    REDIS_KEY = "analyst:weights"
    TTL_SEC = 86400

    @staticmethod
    def compute_weights(
        trade_decisions: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, float]]:
        """Compute per-regime and per-session analyst weights.

        Input decisions must contain:
          - regime, session
          - analyst_signals: {"technical": bias, "fundamental": bias, ...}
          - outcome: 1 (win) or 0 (loss)
        """
        if not trade_decisions:
            return {}

        # Group by regime
        regime_groups = {}
        session_groups = {}
        for d in trade_decisions:
            regime = d.get("regime", "unknown")
            session = d.get("session", "unknown")
            regime_groups.setdefault(regime, []).append(d)
            session_groups.setdefault(session, []).append(d)

        regime_weights = {}
        for regime, decisions in regime_groups.items():
            regime_weights[regime] = AnalystWeightOptimizer._optimize(decisions)

        session_weights = {}
        for session, decisions in session_groups.items():
            session_weights[session] = AnalystWeightOptimizer._optimize(decisions)

        return {
            "by_regime": regime_weights,
            "by_session": session_weights,
            "default": DEFAULT_WEIGHTS,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _optimize(decisions: List[Dict[str, Any]]) -> Dict[str, float]:
        """Simple heuristic: weight proportional to directional accuracy."""
        analyst_names = ["technical", "fundamental", "sentiment", "macro"]
        correct = {a: 0 for a in analyst_names}
        total = {a: 0 for a in analyst_names}

        for d in decisions:
            signals = d.get("analyst_signals", {})
            outcome = d.get("outcome", 0)
            for analyst, signal in signals.items():
                if analyst not in analyst_names:
                    continue
                total[analyst] += 1
                # Signal matches outcome if: bullish + win OR bearish + loss (proxy)
                # This is a simplification; true optimization needs full P&L attribution
                if (signal == "bullish" and outcome == 1) or (signal == "bearish" and outcome == 0):
                    correct[analyst] += 1

        # Laplace smoothing + normalize
        weights = {}
        for a in analyst_names:
            acc = (correct[a] + 1) / (total[a] + 2) if total[a] > 0 else 0.5
            weights[a] = acc

        # Normalize to sum to 1.0
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: round(v / total_weight, 3) for k, v in weights.items()}
        else:
            weights = DEFAULT_WEIGHTS.copy()

        return weights

    @staticmethod
    def get_weights_for_context(
        weights_dict: Dict[str, Any],
        regime: str = "unknown",
        session: str = "unknown",
    ) -> Dict[str, float]:
        """Return the best weights for a given regime + session."""
        by_regime = weights_dict.get("by_regime", {})
        by_session = weights_dict.get("by_session", {})

        # Prefer regime weights; fall back to session; then default
        if regime in by_regime:
            return by_regime[regime]
        if session in by_session:
            return by_session[session]
        return weights_dict.get("default", DEFAULT_WEIGHTS)

    async def cache_weights(self, weights: Dict[str, Any]) -> None:
        try:
            import redis.asyncio as aioredis
            from app.config import get_settings
            r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
            await r.set(self.REDIS_KEY, json.dumps(weights), ex=self.TTL_SEC)
            await r.close()
        except Exception:
            logger.warning("Failed to cache analyst weights", exc_info=True)

    async def get_cached_weights(self) -> Optional[Dict[str, Any]]:
        try:
            import redis.asyncio as aioredis
            from app.config import get_settings
            r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
            raw = await r.get(self.REDIS_KEY)
            await r.close()
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("Analyst weights cache miss", exc_info=True)
        return None

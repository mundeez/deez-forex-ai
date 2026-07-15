"""PatternExtractor — identify recurring trade setups and compute priors.

Scans historical candles + trade outcomes to find:
- Which patterns precede winning trades vs losing trades
- Session-specific win rates
- Regime-specific win rates

Outputs are cached in Redis as JSON for fast lookup by the AI pipeline.
"""
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger("app.services.pattern_extractor")


class PatternExtractor:
    """Extract pattern priors from historical trade + market data."""

    REDIS_KEY = "pattern:priors"
    TTL_SEC = 86400  # 24 hours

    @staticmethod
    def compute_pattern_priors(
        trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compute win-rate statistics by pattern, session, and regime.

        Input: list of trade dicts with keys:
          - symbol, direction, pnl, regime, session, pattern_tags (list)
        """
        if not trades:
            return {}

        # Overall stats
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        total = len(trades)
        win_rate = len(wins) / total if total > 0 else 0.0
        avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0.0
        avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0.0

        # By regime
        regime_stats = {}
        regimes = set(t.get("regime", "unknown") for t in trades)
        for regime in regimes:
            subset = [t for t in trades if t.get("regime") == regime]
            r_wins = [t for t in subset if t.get("pnl", 0) > 0]
            regime_stats[regime] = {
                "count": len(subset),
                "win_rate": round(len(r_wins) / len(subset), 3) if subset else 0.0,
                "avg_pnl": round(np.mean([t["pnl"] for t in subset]), 2) if subset else 0.0,
            }

        # By session
        session_stats = {}
        sessions = set(t.get("session", "unknown") for t in trades)
        for session in sessions:
            subset = [t for t in trades if t.get("session") == session]
            s_wins = [t for t in subset if t.get("pnl", 0) > 0]
            session_stats[session] = {
                "count": len(subset),
                "win_rate": round(len(s_wins) / len(subset), 3) if subset else 0.0,
                "avg_pnl": round(np.mean([t["pnl"] for t in subset]), 2) if subset else 0.0,
            }

        # By pattern tag
        tag_stats = {}
        all_tags = set()
        for t in trades:
            all_tags.update(t.get("pattern_tags", []))
        for tag in all_tags:
            subset = [t for t in trades if tag in t.get("pattern_tags", [])]
            t_wins = [t for t in subset if t.get("pnl", 0) > 0]
            tag_stats[tag] = {
                "count": len(subset),
                "win_rate": round(len(t_wins) / len(subset), 3) if subset else 0.0,
                "avg_pnl": round(np.mean([t["pnl"] for t in subset]), 2) if subset else 0.0,
            }

        # By symbol
        symbol_stats = {}
        symbols = set(t.get("symbol", "unknown") for t in trades)
        for sym in symbols:
            subset = [t for t in trades if t.get("symbol") == sym]
            s_wins = [t for t in subset if t.get("pnl", 0) > 0]
            symbol_stats[sym] = {
                "count": len(subset),
                "win_rate": round(len(s_wins) / len(subset), 3) if subset else 0.0,
                "avg_pnl": round(np.mean([t["pnl"] for t in subset]), 2) if subset else 0.0,
            }

        # By symbol + direction
        pair_dir_stats = {}
        for sym in symbols:
            for direction in ("BUY", "SELL"):
                subset = [t for t in trades if t.get("symbol") == sym and t.get("direction", "").upper() == direction]
                if subset:
                    s_wins = [t for t in subset if t.get("pnl", 0) > 0]
                    pair_dir_stats[f"{sym}_{direction}"] = {
                        "count": len(subset),
                        "win_rate": round(len(s_wins) / len(subset), 3),
                        "avg_pnl": round(np.mean([t["pnl"] for t in subset]), 2),
                    }

        priors = {
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "total_trades": total,
            "overall_win_rate": round(win_rate, 3),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(avg_win * win_rate + avg_loss * (1 - win_rate), 2),
            "by_regime": regime_stats,
            "by_session": session_stats,
            "by_pattern_tag": tag_stats,
            "by_symbol": symbol_stats,
            "by_symbol_direction": pair_dir_stats,
        }

        logger.info(
            "Pattern priors computed: %d trades, wr=%.2f%%, expectancy=%.2f",
            total, win_rate * 100, priors["expectancy"],
        )
        return priors

    async def cache_priors(self, priors: Dict[str, Any]) -> None:
        try:
            import redis.asyncio as aioredis
            from app.config import get_settings
            r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
            await r.set(self.REDIS_KEY, json.dumps(priors), ex=self.TTL_SEC)
            await r.close()
        except Exception:
            logger.warning("Failed to cache pattern priors", exc_info=True)

    async def get_cached_priors(self) -> Optional[Dict[str, Any]]:
        try:
            import redis.asyncio as aioredis
            from app.config import get_settings
            r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
            raw = await r.get(self.REDIS_KEY)
            await r.close()
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("Pattern priors cache miss", exc_info=True)
        return None

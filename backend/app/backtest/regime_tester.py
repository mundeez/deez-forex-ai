"""RegimeBacktester — evaluate strategy performance per market regime.

Segments trade history by detected regime and compares metrics.
"""
import logging
from typing import Dict, Any, List
from collections import defaultdict

import numpy as np

logger = logging.getLogger("app.backtest.regime_tester")


class RegimeBacktester:
    """Compare strategy performance across trending, ranging, volatile, etc."""

    @staticmethod
    def run(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Group trades by regime and compute per-regime metrics."""
        if not trades:
            return {}

        regimes = defaultdict(list)
        for t in trades:
            regime = t.get("regime", "unknown")
            regimes[regime].append(t)

        results = {}
        for regime, subset in regimes.items():
            pnls = [t.get("pnl", 0) for t in subset]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]

            gross_profit = sum(wins) if wins else 0
            gross_loss = abs(sum(losses)) if losses else 1e-9
            pf = gross_profit / gross_loss

            results[regime] = {
                "count": len(subset),
                "win_rate": round(len(wins) / len(subset), 3) if subset else 0,
                "profit_factor": round(pf, 2),
                "avg_pnl": round(np.mean(pnls), 2) if pnls else 0,
                "median_pnl": round(np.median(pnls), 2) if pnls else 0,
                "max_drawdown": round(RegimeBacktester._max_dd(pnls), 2),
            }

        logger.info("RegimeBacktester: evaluated %d regimes", len(results))
        return results

    @staticmethod
    def _max_dd(pnls: List[float]) -> float:
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        dd = cumulative - running_max
        return float(np.min(dd)) if len(dd) > 0 else 0.0

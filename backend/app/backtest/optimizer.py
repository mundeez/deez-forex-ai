"""Strategy optimizer — walk-forward grid search over parameter space.

Optimizes: confidence_threshold, min_risk_reward, atr_sl_mult, atr_tp_mult
per pair × session × strategy_mode. Stores best params in optimization_runs
and writes winning params back to settings.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from app.backtest.engine import BacktestEngine
from app.config import get_settings
from app.utils.time import utc_now
from app.database import get_celery_session
from app import models

settings = get_settings()
logger = logging.getLogger("app.backtest.optimizer")

# Default parameter grids
DEFAULT_PARAM_GRID = {
    "confidence_threshold": [0.40, 0.50, 0.55, 0.60, 0.70],
    "min_risk_reward": [1.0, 1.5, 2.0, 2.5, 3.0],
    "atr_sl_mult": [1.0, 1.5, 2.0, 2.5],
    "atr_tp_mult": [2.0, 3.0, 4.0, 5.0, 6.0],
}


def _fitness(result: Dict[str, Any]) -> float:
    """Combined fitness: Sharpe * win_rate - drawdown_penalty."""
    sharpe = result.get("sharpe_ratio", 0)
    wr = result.get("win_rate", 0) / 100.0
    dd = result.get("max_drawdown_pct", 0)
    trades = result.get("total_trades", 0)
    if trades < 10:
        return -999.0  # Not enough trades
    return sharpe * wr - (dd / 100.0)


class StrategyOptimizer:
    """Walk-forward grid search optimizer."""

    def __init__(self, param_grid: Optional[Dict[str, List[float]]] = None):
        self.param_grid = param_grid or DEFAULT_PARAM_GRID
        self.engine = BacktestEngine()

    async def optimize_symbol(
        self,
        symbol: str,
        strategy_mode: str = "scalping",
        train_days: int = 90,
        test_days: int = 30,
        use_v2: bool = False,
    ) -> Dict[str, Any]:
        """Run walk-forward optimization for a single symbol.

        Train on [now-train_days-test_days, now-test_days],
        test on [now-test_days, now].
        """
        now = utc_now()
        train_end = now - timedelta(days=test_days)
        train_start = train_end - timedelta(days=train_days)
        test_start = train_end

        best_fitness = -999.0
        best_params = {}
        best_train_result = {}
        total_backtests = 0

        # Cartesian product of param grid
        from itertools import product
        keys = list(self.param_grid.keys())
        values = [self.param_grid[k] for k in keys]

        for combo in product(*values):
            params = dict(zip(keys, combo))
            try:
                train_result = await self.engine.run(
                    symbol=symbol,
                    start=train_start,
                    end=train_end,
                    strategy_mode=strategy_mode,
                    use_v2=use_v2,
                    params=params,
                )
                if "error" in train_result:
                    continue
                total_backtests += 1
                fit = _fitness(train_result)
                if fit > best_fitness:
                    best_fitness = fit
                    best_params = params
                    best_train_result = train_result
            except Exception as exc:
                logger.warning("Backtest failed for %s with params %s: %s", symbol, params, exc)

        # Test on hold-out period
        test_result = {}
        if best_params:
            try:
                test_result = await self.engine.run(
                    symbol=symbol,
                    start=test_start,
                    end=now,
                    strategy_mode=strategy_mode,
                    use_v2=use_v2,
                    params=best_params,
                )
            except Exception as exc:
                logger.warning("Test backtest failed for %s: %s", symbol, exc)

        # Persist
        async with get_celery_session()() as db:
            run = models.OptimizationRun(
                symbol=symbol,
                strategy_mode=strategy_mode,
                start_date=train_start,
                end_date=now,
                params_grid={k: list(v) for k, v in self.param_grid.items()},
                best_params=best_params,
                fitness=round(best_fitness, 4),
                total_backtests=total_backtests,
            )
            db.add(run)
            await db.commit()

        return {
            "symbol": symbol,
            "strategy_mode": strategy_mode,
            "best_params": best_params,
            "fitness": round(best_fitness, 4),
            "train_result": best_train_result,
            "test_result": test_result,
            "total_backtests": total_backtests,
        }

    async def run_all(
        self,
        symbols: List[str] = None,
        strategy_modes: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """Optimize all symbol × strategy_mode combinations."""
        symbols = symbols or ["EURUSD", "GBPUSD", "USDJPY"]
        strategy_modes = strategy_modes or ["scalping", "day_trading"]
        results = []
        for symbol in symbols:
            for mode in strategy_modes:
                try:
                    r = await self.optimize_symbol(symbol, mode)
                    results.append(r)
                except Exception as exc:
                    logger.error("Optimization failed for %s/%s: %s", symbol, mode, exc, exc_info=True)
        return results

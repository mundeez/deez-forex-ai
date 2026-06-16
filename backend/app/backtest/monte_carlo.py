"""MonteCarloSimulator — bootstrap equity curve to estimate tail risks.

Resamples daily returns with replacement to generate alternative histories.
Reports: ruin probability, max drawdown distribution, profit factor stability.
"""
import logging
from typing import Dict, Any, List

import numpy as np

logger = logging.getLogger("app.backtest.monte_carlo")


class MonteCarloSimulator:
    """Monte Carlo simulation for trading strategy risk assessment."""

    @staticmethod
    def run(
        daily_returns: List[float],
        n_runs: int = 5000,
        initial_equity: float = 1000.0,
        ruin_threshold: float = 700.0,
    ) -> Dict[str, Any]:
        """Bootstrap daily returns to estimate risk metrics.

        Args:
            daily_returns: list of daily P&L values
            n_runs: number of bootstrap simulations
            initial_equity: starting account balance
            ruin_threshold: equity level considered ruin
        """
        if len(daily_returns) < 10:
            logger.warning("MonteCarlo: insufficient returns (%d days)", len(daily_returns))
            return {}

        returns = np.array(daily_returns)
        n_days = len(returns)

        ruin_count = 0
        max_dd_samples = []
        final_equity_samples = []
        pf_samples = []

        for _ in range(n_runs):
            sampled = np.random.choice(returns, size=n_days, replace=True)
            equity = initial_equity + np.cumsum(sampled)

            # Ruin check
            if np.min(equity) < ruin_threshold:
                ruin_count += 1

            # Max drawdown
            running_max = np.maximum.accumulate(equity)
            dd = np.min((equity - running_max) / running_max * 100)
            max_dd_samples.append(dd)

            final_equity_samples.append(equity[-1])

            # Profit factor
            wins = np.sum(sampled[sampled > 0])
            losses = abs(np.sum(sampled[sampled < 0]))
            pf = wins / losses if losses > 0 else 0
            pf_samples.append(pf)

        return {
            "n_runs": n_runs,
            "n_days": n_days,
            "ruin_probability": round(ruin_count / n_runs, 3),
            "median_max_dd_pct": round(np.median(max_dd_samples), 2),
            "worst_max_dd_pct": round(np.min(max_dd_samples), 2),
            "median_final_equity": round(np.median(final_equity_samples), 2),
            "median_profit_factor": round(np.median([p for p in pf_samples if p > 0]), 2),
            "pf_std": round(np.std([p for p in pf_samples if p > 0]), 2),
            "equity_std": round(np.std(final_equity_samples), 2),
        }

"""WalkForwardTester — time-series cross-validation for trading strategies.

Trains on N months, tests on 1 month, rolls forward.
Prevents data leakage by strict time-based splits.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from app.backtest.data_guard import DataLeakageGuard

logger = logging.getLogger("app.backtest.walk_forward")


class WalkForwardTester:
    """Walk-forward analysis: train/test on expanding or rolling windows."""

    @staticmethod
    def run(
        decisions: List[Dict[str, Any]],
        train_months: int = 6,
        test_months: int = 1,
        min_trades: int = 30,
    ) -> List[Dict[str, Any]]:
        """Run walk-forward backtest over decision history.

        Input: list of dicts with 'timestamp' (datetime), 'pnl', 'direction', 'decision'
        Returns: list of window results with PF, win_rate, Sharpe, etc.
        """
        if len(decisions) < min_trades:
            logger.warning("WalkForward: insufficient data (%d trades)", len(decisions))
            return []

        df = pd.DataFrame(decisions)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

        # Create monthly windows
        start = df["timestamp"].min()
        end = df["timestamp"].max()
        windows = []

        current = start
        while current + pd.DateOffset(months=train_months + test_months) <= end:
            train_end = current + pd.DateOffset(months=train_months)
            test_end = train_end + pd.DateOffset(months=test_months)

            train_df = df[(df["timestamp"] >= current) & (df["timestamp"] < train_end)]
            test_df = df[(df["timestamp"] >= train_end) & (df["timestamp"] < test_end)]

            if len(test_df) < 5:
                current += pd.DateOffset(months=test_months)
                continue

            result = WalkForwardTester._evaluate_window(train_df, test_df)
            result["window_start"] = current.isoformat()
            result["window_end"] = test_end.isoformat()
            windows.append(result)
            current += pd.DateOffset(months=test_months)

        logger.info("WalkForward: %d windows evaluated", len(windows))
        return windows

    @staticmethod
    def _evaluate_window(train_df: pd.DataFrame, test_df: pd.DataFrame) -> Dict[str, Any]:
        """Compute metrics for a single train/test window."""
        wins = test_df[test_df["pnl"] > 0]
        losses = test_df[test_df["pnl"] <= 0]
        total = len(test_df)

        gross_profit = wins["pnl"].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses["pnl"].sum()) if len(losses) > 0 else 1e-9
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        returns = test_df["pnl"].tolist()
        sharpe = 0.0
        if len(returns) > 1:
            mean_ret = np.mean(returns)
            std_ret = np.std(returns)
            if std_ret > 0:
                sharpe = mean_ret / std_ret * np.sqrt(len(returns))

        return {
            "train_samples": len(train_df),
            "test_samples": total,
            "win_rate": round(len(wins) / total, 3) if total > 0 else 0,
            "profit_factor": round(profit_factor, 2),
            "sharpe": round(sharpe, 2),
            "avg_pnl": round(test_df["pnl"].mean(), 2) if total > 0 else 0,
            "max_drawdown": round(WalkForwardTester._max_drawdown(test_df["pnl"]), 2),
        }

    @staticmethod
    def _max_drawdown(returns: pd.Series) -> float:
        """Compute max drawdown from P&L series."""
        cumulative = returns.cumsum()
        running_max = cumulative.cummax()
        drawdown = cumulative - running_max
        return drawdown.min()

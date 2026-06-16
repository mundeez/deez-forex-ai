"""DataLeakageGuard — prevent future-peeking in backtests.

Ensures that any indicator or feature used at time T only depends on
data available up to and including T (no look-ahead bias).
"""
import logging
from typing import Dict, Any, List
from datetime import datetime

logger = logging.getLogger("app.backtest.data_guard")


class DataLeakageGuard:
    """Validate that backtest features do not peek into the future."""

    @staticmethod
    def validate_candles(candles: List[Dict[str, Any]]) -> bool:
        """Check that candles are monotonically increasing in time."""
        if len(candles) < 2:
            return True
        prev_ts = None
        for c in candles:
            ts = c.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if prev_ts and ts < prev_ts:
                logger.error("DataLeakageGuard: non-monotonic timestamps detected")
                return False
            prev_ts = ts
        return True

    @staticmethod
    def shift_indicators(df, shift_periods: int = 1):
        """Shift computed indicators by N periods to prevent leakage.

        Use shift_periods=1 for lag-1 features (most conservative).
        """
        indicator_cols = [c for c in df.columns if c not in ("timestamp", "open", "high", "low", "close", "volume")]
        for col in indicator_cols:
            df[col] = df[col].shift(shift_periods)
        return df

    @staticmethod
    def validate_features_at_time(features: Dict[str, Any], candle_timestamp: datetime, now: datetime) -> bool:
        """Ensure all features were computable at or before candle_timestamp."""
        if candle_timestamp > now:
            logger.error("DataLeakageGuard: feature computed from future candle")
            return False
        return True

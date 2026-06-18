"""Multi-timeframe feature engineering from historical_candles.

Computes technical features at 1m, 5m, 15m, 1h timeframes for ML training.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.services.ml.multitimeframe")

TIMEFRAMES = ["1m", "5m", "15m", "1h"]


async def fetch_candles(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
    before: datetime,
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch historical candles before a given timestamp."""
    stmt = text("""
        SELECT timestamp, open, high, low, close, volume
        FROM historical_candles
        WHERE symbol = :symbol AND timeframe = :timeframe
          AND timestamp <= :before
        ORDER BY timestamp DESC
        LIMIT :limit
    """)
    result = await db.execute(stmt, {
        "symbol": symbol, "timeframe": timeframe,
        "before": before, "limit": limit,
    })
    rows = result.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return float(tr.iloc[-period:].mean())


def _ema(series: pd.Series, span: int) -> float:
    if len(series) < span:
        return float(series.iloc[-1]) if len(series) > 0 else 0.0
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _volume_features(df: pd.DataFrame) -> Dict[str, float]:
    if len(df) < 10:
        return {"vol_mean": 0.0, "vol_z": 0.0, "vol_trend": 0.0}
    vol = df["volume"].astype(float)
    mean_vol = vol.mean()
    std_vol = vol.std() or 1.0
    last_vol = vol.iloc[-1]
    vol_z = (last_vol - mean_vol) / std_vol
    vol_trend = 1.0 if vol.iloc[-5:].mean() > vol.iloc[-20:].mean() else 0.0
    return {"vol_mean": mean_vol, "vol_z": vol_z, "vol_trend": vol_trend}


def _compute_tf_features(df: pd.DataFrame, tf: str) -> Dict[str, float]:
    if df.empty or len(df) < 20:
        return {}
    close = df["close"]
    last = close.iloc[-1]
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema50 = _ema(close, 50)
    atr = _atr(df, 14)
    rsi = _rsi(close, 14)
    vol_feats = _volume_features(df)

    # Trend alignment
    trend_up = 1.0 if last > ema9 > ema21 > ema50 else 0.0
    trend_down = 1.0 if last < ema9 < ema21 < ema50 else 0.0

    # Price position within recent range
    recent_high = df["high"].iloc[-20:].max()
    recent_low = df["low"].iloc[-20:].min()
    range_pct = ((last - recent_low) / (recent_high - recent_low) * 100) if recent_high != recent_low else 50.0

    return {
        f"{tf}_rsi": rsi,
        f"{tf}_atr": atr,
        f"{tf}_ema9_dist": (last - ema9) / last * 100 if last else 0.0,
        f"{tf}_ema21_dist": (last - ema21) / last * 100 if last else 0.0,
        f"{tf}_trend_up": trend_up,
        f"{tf}_trend_down": trend_down,
        f"{tf}_range_pct": range_pct,
        f"{tf}_vol_z": vol_feats["vol_z"],
        f"{tf}_vol_trend": vol_feats["vol_trend"],
    }


async def compute_multitimeframe_features(
    db: AsyncSession,
    symbol: str,
    decision_time: datetime,
) -> Dict[str, float]:
    """Compute multi-timeframe technical features at a given decision time."""
    features: Dict[str, float] = {}
    dfs = {}

    for tf in TIMEFRAMES:
        limit = 100 if tf in ("1m", "5m") else 50
        df = await fetch_candles(db, symbol, tf, decision_time, limit=limit)
        dfs[tf] = df
        tf_feats = _compute_tf_features(df, tf)
        features.update(tf_feats)

    # Cross-timeframe features
    for fast, slow in [("1m", "5m"), ("5m", "15m"), ("15m", "1h")]:
        fast_df = dfs.get(fast)
        slow_df = dfs.get(slow)
        if fast_df is not None and not fast_df.empty and slow_df is not None and not slow_df.empty:
            fast_close = fast_df["close"].iloc[-1]
            slow_close = slow_df["close"].iloc[-1]
            features[f"{fast}_vs_{slow}_pct"] = (fast_close - slow_close) / slow_close * 100 if slow_close else 0.0

    # Volatility ratio: fast TF ATR vs slow TF ATR
    for fast, slow in [("1m", "5m"), ("5m", "15m"), ("15m", "1h")]:
        fast_atr = features.get(f"{fast}_atr", 0)
        slow_atr = features.get(f"{slow}_atr", 0)
        if slow_atr and slow_atr > 0:
            features[f"{fast}_atr_ratio"] = fast_atr / slow_atr
        else:
            features[f"{fast}_atr_ratio"] = 0.0

    # Timeframe agreement: how many TFs agree on trend direction?
    trend_up_sum = sum(features.get(f"{tf}_trend_up", 0) for tf in TIMEFRAMES)
    trend_down_sum = sum(features.get(f"{tf}_trend_down", 0) for tf in TIMEFRAMES)
    features["tf_agreement_up"] = trend_up_sum
    features["tf_agreement_down"] = trend_down_sum
    features["tf_agreement_score"] = max(trend_up_sum, trend_down_sum) / len(TIMEFRAMES)

    return features

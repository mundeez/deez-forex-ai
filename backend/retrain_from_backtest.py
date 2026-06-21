#!/usr/bin/env python3
"""Retrain EntryQualityModel and TeamMetaModel using backtest trade outcomes.

Run inside backend container:
  docker compose exec backend python /app/retrain_from_backtest.py
"""
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, "/app")

from app.database import get_celery_session
from app.services.ml.entry_model import EntryQualityModel
from app.services.ml.team_meta_model import TeamMetaModel
from app.services.ml.multitimeframe_features import compute_multitimeframe_features

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("retrain_backtest")

TRADES_FILE = "/app/backtest_checkpoints/20260619_142018_trades.jsonl"


def load_backtest_trades():
    lines = open(TRADES_FILE).readlines()
    return [json.loads(l) for l in lines if l.strip()]


async def build_entry_features(db, trade):
    """Build feature vector for a backtest trade using historical candles."""
    symbol = trade["symbol"]
    ts = pd.to_datetime(trade["timestamp"])
    start = ts - timedelta(hours=24)
    
    # Load 5m candles before trade
    stmt = text("""
        SELECT timestamp, open, high, low, close, volume
        FROM historical_candles
        WHERE symbol = :symbol AND timeframe = '5m'
          AND timestamp >= :start AND timestamp < :end
        ORDER BY timestamp DESC
        LIMIT 288
    """)
    result = await db.execute(stmt, {"symbol": symbol, "start": start, "end": ts})
    rows = result.fetchall()
    
    if len(rows) < 50:
        return None
    
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.sort_values("timestamp")
    
    # Basic technical features
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    
    features = {
        "symbol": symbol,
        "direction": 1 if trade["direction"] == "buy" else 0,
        "label": 1 if trade["pnl_usd"] > 0 else 0,
        "confidence": trade.get("confidence", 0.5),
        "entry_price": trade["entry_price"],
        "sl_distance_pct": abs(trade["entry_price"] - trade["stop_loss"]) / trade["entry_price"] * 100,
        "tp_distance_pct": abs(trade["take_profit"] - trade["entry_price"]) / trade["entry_price"] * 100,
        "rr_ratio": abs(trade["take_profit"] - trade["entry_price"]) / max(abs(trade["entry_price"] - trade["stop_loss"]), 1e-9),
        # Technical indicators
        "rsi_14": _rsi(close, 14),
        "ema_9_dist": (close[-1] - _ema(close, 9)[-1]) / close[-1] * 100,
        "ema_21_dist": (close[-1] - _ema(close, 21)[-1]) / close[-1] * 100,
        "atr_14": _atr(high, low, close, 14),
        "volatility_20": np.std(close[-20:]) / np.mean(close[-20:]) * 100,
        "volume_zscore": (df["volume"].iloc[-1] - df["volume"].mean()) / max(df["volume"].std(), 1e-9),
        "trend_5": 1 if close[-1] > close[-5] else 0,
        "trend_20": 1 if close[-1] > close[-20] else 0,
        "price_position": (close[-1] - low[-20:].min()) / (high[-20:].max() - low[-20:].min() + 1e-9),
        "hour": ts.hour,
        "day_of_week": ts.weekday(),
    }
    
    # Multi-timeframe features
    try:
        mt = await compute_multitimeframe_features(db, symbol, ts)
        features.update(mt)
    except Exception as e:
        logger.debug("MT features failed for %s %s: %s", symbol, ts, e)
    
    return features


def _rsi(prices, period=14):
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:]) if len(gains) >= period else 1e-9
    avg_loss = np.mean(losses[-period:]) if len(losses) >= period else 1e-9
    rs = avg_gain / max(avg_loss, 1e-9)
    return 100 - (100 / (1 + rs))


def _ema(prices, period):
    alpha = 2 / (period + 1)
    ema = [prices[0]]
    for p in prices[1:]:
        ema.append(ema[-1] + alpha * (p - ema[-1]))
    return np.array(ema)


def _atr(high, low, close, period=14):
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    return np.mean(tr[-period:]) if len(tr) >= period else np.mean(tr)


async def retrain_entry_model(db, trades):
    logger.info("Building entry features for %d trades...", len(trades))
    features_list = []
    for i, trade in enumerate(trades):
        if i % 100 == 0:
            logger.info("  Processing trade %d/%d", i, len(trades))
        f = await build_entry_features(db, trade)
        if f:
            features_list.append(f)
    
    if len(features_list) < 100:
        logger.error("Only %d valid feature vectors, need at least 100", len(features_list))
        return None
    
    df = pd.DataFrame(features_list)
    logger.info("Training EntryQualityModel on %d samples...", len(df))
    
    model = EntryQualityModel()
    metrics = model.train(df, label_col="label", test_size=0.2)
    
    logger.info("EntryQualityModel retrained: train_auc=%.3f test_auc=%.3f", 
                metrics["train_auc"], metrics["test_auc"])
    return metrics


async def retrain_team_meta_model(db, trades):
    """Build simplified team meta features from backtest outcomes."""
    logger.info("Building team meta features for %d trades...", len(trades))
    
    records = []
    for trade in trades:
        records.append({
            "label": 1 if trade["pnl_usd"] > 0 else 0,
            "confidence": trade.get("confidence", 0.5),
            "direction": 1 if trade["direction"] == "buy" else 0,
            "rr_ratio": abs(trade["take_profit"] - trade["entry_price"]) / max(abs(trade["entry_price"] - trade["stop_loss"]), 1e-9),
            "sl_distance_pct": abs(trade["entry_price"] - trade["stop_loss"]) / trade["entry_price"] * 100,
            "tp_distance_pct": abs(trade["take_profit"] - trade["entry_price"]) / trade["entry_price"] * 100,
            "hour": pd.to_datetime(trade["timestamp"]).hour,
            "day_of_week": pd.to_datetime(trade["timestamp"]).weekday(),
            "model_used": trade.get("model_used", ""),
        })
    
    df = pd.DataFrame(records)
    
    # One-hot encode model_used
    if "model_used" in df.columns:
        model_dummies = pd.get_dummies(df["model_used"], prefix="model")
        df = pd.concat([df.drop("model_used", axis=1), model_dummies], axis=1)
    
    logger.info("Training TeamMetaModel on %d samples...", len(df))
    
    model = TeamMetaModel()
    metrics = model.train(df, label_col="label", test_size=0.2)
    
    logger.info("TeamMetaModel retrained: train_auc=%.3f test_auc=%.3f", 
                metrics["train_auc"], metrics["test_auc"])
    return metrics


async def main():
    logger.info("=" * 60)
    logger.info("RETRAINING FROM BACKTEST TRADES")
    logger.info("=" * 60)
    
    trades = load_backtest_trades()
    logger.info("Loaded %d backtest trades", len(trades))
    
    wins = [t for t in trades if t["pnl_usd"] > 0]
    logger.info("Win rate: %.1f%% (%d/%d)", len(wins)/len(trades)*100, len(wins), len(trades))
    
    async with get_celery_session()() as db:
        entry_metrics = await retrain_entry_model(db, trades)
        team_metrics = await retrain_team_meta_model(db, trades)
    
    logger.info("=" * 60)
    logger.info("RETRAINING COMPLETE")
    logger.info("=" * 60)
    if entry_metrics:
        logger.info("EntryQualityModel — train_auc: %.3f, test_auc: %.3f", 
                    entry_metrics["train_auc"], entry_metrics["test_auc"])
    if team_metrics:
        logger.info("TeamMetaModel — train_auc: %.3f, test_auc: %.3f",
                    team_metrics["train_auc"], team_metrics["test_auc"])


if __name__ == "__main__":
    asyncio.run(main())

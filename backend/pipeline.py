"""pipeline.py — Feature engineering and calibration pipeline for the meta-classifier.

Ingests historical v2 AI decision records, engineers calibrated features,
and outputs a clean DataFrame ready for XGBoost training.

Usage:
    docker compose exec -T backend python3 /app/pipeline.py
"""
import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pipeline")


# ------------------------------------------------------------------------------
# DB helper (asyncpg, runs inside asyncio)
# ------------------------------------------------------------------------------
async def _fetch_rows() -> List[dict]:
    import asyncpg
    db_url = os.environ.get("DATABASE_URL", "")
    # Extract host/port/db/user/pass from asyncpg URL
    # postgresql+asyncpg://user:pass@host:5432/db
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch("""
            SELECT
                d.id AS decision_id,
                d.symbol,
                d.timestamp,
                d.decision,
                d.confidence AS lead_confidence,
                d.analyst_opinions,
                d.verifier_verdict,
                d.verifier_confidence,
                d.verifier_model,
                d.lead_model,
                d.regime,
                d.daily_bias,
                t.id AS trade_id,
                t.pnl,
                t.pnl_pct,
                t.status,
                t.direction,
                t.entry_price,
                t.close_reason
            FROM ai_decisions d
            INNER JOIN trades t ON t.ai_decision_id = d.id
            WHERE d.engine_version = 'v2'
              AND d.analyst_opinions IS NOT NULL
              AND d.timestamp IS NOT NULL
              AND t.status = 'CLOSED'
              AND t.pnl IS NOT NULL
              AND d.lead_model = 'deepseek/deepseek-v4-flash'
            ORDER BY d.timestamp ASC
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def fetch_decisions_with_outcomes() -> pd.DataFrame:
    """Pull v2 ai_decisions joined to their trade outcomes."""
    rows = asyncio.run(_fetch_rows())
    df = pd.DataFrame(rows)
    logger.info("Fetched %d v2 decisions with outcomes", len(df))
    return df


# ------------------------------------------------------------------------------
# JSON extraction helpers
# ------------------------------------------------------------------------------
def _safe_json(val):
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}


def _safe_dict(val):
    """Ensure val is a dict; handles None, str, and already-dict."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}


def _extract_agent_confidence(opinions, domain: str) -> float:
    """Pull confidence_score from a domain analyst's opinion."""
    opinions = _safe_dict(opinions)
    op = opinions.get(domain, {})
    if isinstance(op, dict):
        return float(op.get("confidence_score", 0.0) or 0.0)
    return 0.0


def _extract_agent_bias(opinions, domain: str) -> str:
    opinions = _safe_dict(opinions)
    op = opinions.get(domain, {})
    if isinstance(op, dict):
        return str(op.get("bias", "NEUTRAL")).upper()
    return "NEUTRAL"


def _conviction_score(bias: str, confidence: float) -> float:
    """Map bias + confidence to continuous conviction [-1.0, 1.0]."""
    if bias == "BULLISH":
        return confidence
    if bias == "BEARISH":
        return -1.0 * confidence
    return 0.0


def _verdict_numeric(verdict: str) -> float:
    """Ordinal mapping: APPROVE=1.0, REVISE=0.5, VETO=0.0."""
    mapping = {"APPROVE": 1.0, "REVISE": 0.5, "VETO": 0.0}
    return mapping.get(str(verdict).upper(), 0.0)


# ------------------------------------------------------------------------------
# Probability calibration (fit on train, transform on both)
# ------------------------------------------------------------------------------
def calibrate_isotonic(
    train_conf: np.ndarray,
    train_labels: np.ndarray,
    transform_conf: np.ndarray,
) -> np.ndarray:
    """Fit isotonic regression on training confidence → outcomes, apply to new data."""
    # Ensure arrays are 1D and finite
    train_conf = np.asarray(train_conf, dtype=float)
    train_labels = np.asarray(train_labels, dtype=float)
    mask = np.isfinite(train_conf) & np.isfinite(train_labels)
    train_conf = train_conf[mask]
    train_labels = train_labels[mask]

    if len(train_conf) < 5:
        logger.warning("Too few samples (%d) for isotonic calibration; returning raw confidence", len(train_conf))
        return np.asarray(transform_conf, dtype=float)

    ir = IsotonicRegression(out_of_bounds="clip")
    ir.fit(train_conf.reshape(-1, 1).ravel(), train_labels)
    return ir.predict(np.asarray(transform_conf, dtype=float).reshape(-1, 1).ravel())


def calibrate_platt(
    train_conf: np.ndarray,
    train_labels: np.ndarray,
    transform_conf: np.ndarray,
) -> np.ndarray:
    """Fit Platt scaling (logistic regression) on training confidence → outcomes."""
    train_conf = np.asarray(train_conf, dtype=float).reshape(-1, 1)
    train_labels = np.asarray(train_labels, dtype=float)
    mask = np.isfinite(train_conf.ravel()) & np.isfinite(train_labels)
    train_conf = train_conf[mask]
    train_labels = train_labels[mask]

    if len(train_conf) < 5:
        logger.warning("Too few samples for Platt calibration; returning raw confidence")
        return np.asarray(transform_conf, dtype=float)

    lr = LogisticRegression(solver="lbfgs", max_iter=200)
    lr.fit(train_conf, train_labels)
    return lr.predict_proba(np.asarray(transform_conf, dtype=float).reshape(-1, 1))[:, 1]


# ------------------------------------------------------------------------------
# Core feature engineering
# ------------------------------------------------------------------------------
def build_raw_features(df: pd.DataFrame) -> pd.DataFrame:
    """Parse analyst_opinions JSON and construct raw features."""
    records = []
    for _, row in df.iterrows():
        opinions = _safe_dict(row.get("analyst_opinions"))

        rec = {
            "decision_id": row["decision_id"],
            "timestamp": row["timestamp"],
            "symbol": row["symbol"],
            "trade_id": row["trade_id"],
            # Outcome label: 1 = profitable, 0 = loss or breakeven, None = no trade
            "label": 1.0 if row.get("pnl", 0) and row["pnl"] > 0 else (0.0 if row.get("pnl", 0) is not None else None),
            "pnl": row.get("pnl"),
            "pnl_pct": row.get("pnl_pct"),
            "decision": row.get("decision"),
            "lead_model": row.get("lead_model"),
            # Raw confidence from each agent
            "raw_tech_conf": _extract_agent_confidence(opinions, "technical"),
            "raw_fund_conf": _extract_agent_confidence(opinions, "fundamental"),
            "raw_macro_conf": _extract_agent_confidence(opinions, "macro"),
            "raw_sent_conf": _extract_agent_confidence(opinions, "sentiment"),
            "raw_lead_conf": float(row.get("lead_confidence", 0.0) or 0.0),
            # Bias for fundamental & macro
            "fund_bias": _extract_agent_bias(opinions, "fundamental"),
            "macro_bias": _extract_agent_bias(opinions, "macro"),
            # Verifier
            "verdict": str(row.get("verifier_verdict", "SKIPPED")).upper(),
            "verifier_confidence": float(row.get("verifier_confidence", 0.0) or 0.0),
        }
        records.append(rec)

    out = pd.DataFrame(records)

    # Engineer conviction features (-1.0 to +1.0)
    out["feat_fund_conviction"] = out.apply(
        lambda r: _conviction_score(r["fund_bias"], r["raw_fund_conf"]), axis=1
    )
    out["feat_macro_conviction"] = out.apply(
        lambda r: _conviction_score(r["macro_bias"], r["raw_macro_conf"]), axis=1
    )

    # Verifier score: verdict_numeric * confidence
    out["feat_verifier_score"] = out.apply(
        lambda r: _verdict_numeric(r["verdict"]) * r["verifier_confidence"], axis=1
    )

    return out


def build_calibrated_features(
    df: pd.DataFrame,
    n_splits: int = 5,
    method: str = "isotonic",
) -> pd.DataFrame:
    """Add per-agent calibrated probabilities using out-of-fold TimeSeriesSplit.

    This is the key anti-leakage step: calibration models are fit on training
    folds only and applied to the validation fold.
    """
    df = df.copy().reset_index(drop=True)
    # Need a numeric index for TimeSeriesSplit
    df["_idx"] = np.arange(len(df))

    # Agents whose confidence we calibrate
    agent_cols = [
        ("raw_tech_conf", "feat_tech_prob_calibrated"),
        ("raw_lead_conf", "feat_lead_prob_calibrated"),
        ("raw_sent_conf", "feat_sentiment_prob_calibrated"),
    ]

    for raw_col, cal_col in agent_cols:
        df[cal_col] = np.nan

    tscv = TimeSeriesSplit(n_splits=n_splits)
    for fold, (train_idx, val_idx) in enumerate(tscv.split(df)):
        logger.info("Calibration fold %d: train=%d, val=%d", fold + 1, len(train_idx), len(val_idx))
        train_df = df.iloc[train_idx]
        val_df = df.iloc[val_idx]

        # Filter to rows with trades (need labels for calibration)
        train_labeled = train_df[train_df["label"].notna()]
        if len(train_labeled) < 10:
            logger.warning("Fold %d has only %d labeled samples; skipping calibration", fold + 1, len(train_labeled))
            for raw_col, cal_col in agent_cols:
                df.loc[val_df.index, cal_col] = val_df[raw_col].values
            continue

        for raw_col, cal_col in agent_cols:
            train_conf = train_labeled[raw_col].values.astype(float)
            train_labels = train_labeled["label"].values.astype(float)
            val_conf = val_df[raw_col].values.astype(float)

            if method == "isotonic":
                calibrated = calibrate_isotonic(train_conf, train_labels, val_conf)
            else:
                calibrated = calibrate_platt(train_conf, train_labels, val_conf)

            df.loc[val_df.index, cal_col] = calibrated

    # For the earliest fold(s) that were only training, copy raw confidence as fallback
    for raw_col, cal_col in agent_cols:
        df[cal_col] = df[cal_col].fillna(df[raw_col])
        # Clip to valid probability range
        df[cal_col] = df[cal_col].clip(0.0, 1.0)

    # Interaction feature: lead calibrated * verifier score
    df["feat_interaction_lead_verifier"] = (
        df["feat_lead_prob_calibrated"] * df["feat_verifier_score"]
    )

    df = df.drop(columns=["_idx"], errors="ignore")
    return df


def run_pipeline(
    n_splits: int = 5,
    method: str = "isotonic",
) -> pd.DataFrame:
    """Full pipeline: fetch → engineer → calibrate."""
    logger.info("=== Stage 1: Fetching raw decisions ===")
    raw_df = fetch_decisions_with_outcomes()

    logger.info("=== Stage 2: Engineering raw features ===")
    features = build_raw_features(raw_df)
    n_trades = features["label"].notna().sum()
    n_wins = (features["label"] == 1.0).sum()
    logger.info("Labeled trades: %d (wins=%d, win_rate=%.1f%%)", n_trades, n_wins, 100 * n_wins / max(n_trades, 1))

    logger.info("=== Stage 3: Out-of-fold probability calibration (%s) ===", method)
    calibrated = build_calibrated_features(features, n_splits=n_splits, method=method)

    # Final feature matrix
    feature_cols = [
        "feat_tech_prob_calibrated",
        "feat_lead_prob_calibrated",
        "feat_fund_conviction",
        "feat_macro_conviction",
        "feat_sentiment_prob_calibrated",
        "feat_verifier_score",
        "feat_interaction_lead_verifier",
    ]

    # Keep only rows with known labels for training
    trainable = calibrated[calibrated["label"].notna()].copy()
    trainable = trainable.reset_index(drop=True)

    logger.info("=== Pipeline complete ===")
    logger.info("Trainable samples: %d", len(trainable))
    logger.info("Feature columns: %s", feature_cols)
    return trainable


if __name__ == "__main__":
    df = run_pipeline()
    out_path = "/app/data/meta_features.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    logger.info("Saved feature matrix to %s (%d rows)", out_path, len(df))

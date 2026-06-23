"""pipeline.py — Enhanced feature engineering + model-specific Platt calibration.

Ingests historical v2 AI decision records, engineers ~18 features from
analyst opinions + verifier signals, applies model-specific Platt scaling,
and outputs a clean DataFrame ready for XGBoost training.

Usage:
    docker compose exec -T backend python3 /app/pipeline.py
"""
import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pipeline")

DOMAINS = ["technical", "fundamental", "sentiment", "macro"]


# ------------------------------------------------------------------------------
# DB helper (asyncpg, runs inside asyncio)
# ------------------------------------------------------------------------------
async def _fetch_rows() -> List[dict]:
    import asyncpg
    db_url = os.environ.get("DATABASE_URL", "")
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
    rows = asyncio.run(_fetch_rows())
    df = pd.DataFrame(rows)
    logger.info("Fetched %d production-suite decisions with outcomes", len(df))
    return df


# ------------------------------------------------------------------------------
# JSON helpers
# ------------------------------------------------------------------------------
def _safe_dict(val):
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


# ------------------------------------------------------------------------------
# Feature engineering (expanded ~18 features)
# ------------------------------------------------------------------------------
def _extract_all_features(opinions: Any, lead_conf: float, verdict: str, verifier_conf: float) -> Dict[str, float]:
    """Extract the full feature vector from one decision's analyst opinions."""
    opinions = _safe_dict(opinions)
    features: Dict[str, float] = {}

    confidences = []
    biases = []
    risk_warnings = 0
    model_names = []

    for domain in DOMAINS:
        op = opinions.get(domain, {})
        conf = float(op.get("confidence_score", 0.0) or 0.0)
        confidences.append(conf)
        features[f"{domain}_conf"] = conf

        bias = str(op.get("bias", "NEUTRAL")).upper()
        biases.append(bias)
        features[f"{domain}_bull"] = 1.0 if bias == "BULLISH" else 0.0
        features[f"{domain}_bear"] = 1.0 if bias == "BEARISH" else 0.0
        features[f"{domain}_neut"] = 1.0 if bias == "NEUTRAL" else 0.0

        risk = op.get("risk_warning", "")
        if risk and risk.lower() not in ("", "none", "low"):
            risk_warnings += 1
            features[f"{domain}_risk"] = 1.0
        else:
            features[f"{domain}_risk"] = 0.0

        model = op.get("model_used", "")
        if model:
            model_names.append(model)

    # --- Aggregate confidence stats ---
    features["avg_confidence"] = np.mean(confidences) if confidences else 0.0
    features["min_confidence"] = np.min(confidences) if confidences else 0.0
    features["max_confidence"] = np.max(confidences) if confidences else 0.0
    features["conf_std"] = np.std(confidences) if len(confidences) > 1 else 0.0

    # --- Bias agreement (proven predictive in original TeamMetaModel) ---
    bullish_count = sum(1 for b in biases if b == "BULLISH")
    bearish_count = sum(1 for b in biases if b == "BEARISH")
    neutral_count = sum(1 for b in biases if b == "NEUTRAL")
    features["bullish_count"] = float(bullish_count)
    features["bearish_count"] = float(bearish_count)
    features["neutral_count"] = float(neutral_count)
    features["bias_agreement"] = max(bullish_count, bearish_count, neutral_count) / len(DOMAINS)
    features["bias_majority"] = 1.0 if max(bullish_count, bearish_count) >= 3 else 0.0

    # --- Risk ---
    features["total_risk_warnings"] = float(risk_warnings)
    features["any_risk"] = 1.0 if risk_warnings > 0 else 0.0

    # --- Model diversity ---
    features["unique_models"] = float(len(set(model_names)))
    features["model_count"] = float(len(model_names))

    # --- Directional conviction for fundamental & macro ---
    features["feat_fund_conviction"] = _conviction_score(
        _extract_bias(opinions, "fundamental"),
        _extract_confidence(opinions, "fundamental"),
    )
    features["feat_macro_conviction"] = _conviction_score(
        _extract_bias(opinions, "macro"),
        _extract_confidence(opinions, "macro"),
    )

    # --- Verifier features ---
    v_upper = str(verdict).upper()
    features["verifier_approve"] = 1.0 if v_upper == "APPROVE" else 0.0
    features["verifier_revise"] = 1.0 if v_upper == "REVISE" else 0.0
    features["verifier_veto"] = 1.0 if v_upper == "VETO" else 0.0
    features["verifier_skipped"] = 1.0 if v_upper in ("", "SKIPPED", "NONE") else 0.0

    # Verifier conviction score
    verdict_num = {"APPROVE": 1.0, "REVISE": 0.5, "VETO": 0.0}.get(v_upper, 0.0)
    features["feat_verifier_score"] = verdict_num * verifier_conf

    # --- Lead-verifier interaction ---
    features["feat_lead_verifier_raw"] = lead_conf * verifier_conf

    # --- Directional disagreement: technical vs fundamental ---
    tech_bias = _extract_bias(opinions, "technical")
    fund_bias = _extract_bias(opinions, "fundamental")
    features["tech_fund_disagree"] = 1.0 if tech_bias != fund_bias else 0.0

    return features


def _extract_confidence(opinions, domain: str) -> float:
    opinions = _safe_dict(opinions)
    op = opinions.get(domain, {})
    return float(op.get("confidence_score", 0.0) or 0.0) if isinstance(op, dict) else 0.0


def _extract_bias(opinions, domain: str) -> str:
    opinions = _safe_dict(opinions)
    op = opinions.get(domain, {})
    return str(op.get("bias", "NEUTRAL")).upper() if isinstance(op, dict) else "NEUTRAL"


def _conviction_score(bias: str, confidence: float) -> float:
    if bias == "BULLISH":
        return confidence
    if bias == "BEARISH":
        return -1.0 * confidence
    return 0.0


# ------------------------------------------------------------------------------
# Model-specific Platt calibration
# ------------------------------------------------------------------------------
def _fit_platt(train_conf: np.ndarray, train_labels: np.ndarray) -> Optional[LogisticRegression]:
    """Fit a Platt scaler; return None if too few samples."""
    train_conf = np.asarray(train_conf, dtype=float).reshape(-1, 1)
    train_labels = np.asarray(train_labels, dtype=float)
    mask = np.isfinite(train_conf.ravel()) & np.isfinite(train_labels)
    train_conf = train_conf[mask]
    train_labels = train_labels[mask]

    if len(train_conf) < 10:
        return None

    lr = LogisticRegression(solver="lbfgs", max_iter=200)
    lr.fit(train_conf, train_labels)
    return lr


def calibrate_model_specific(
    df: pd.DataFrame,
    raw_col: str,
    cal_col: str,
    model_col: str,
    n_splits: int = 5,
) -> pd.DataFrame:
    """Apply Platt scaling per-model to avoid destroying model-specific signals."""
    df = df.copy().reset_index(drop=True)
    df["_idx"] = np.arange(len(df))
    df[cal_col] = np.nan

    tscv = TimeSeriesSplit(n_splits=n_splits)

    for fold, (train_idx, val_idx) in enumerate(tscv.split(df)):
        train_df = df.iloc[train_idx]
        val_df = df.iloc[val_idx]
        train_labeled = train_df[train_df["label"].notna()]

        if len(train_labeled) < 20:
            logger.warning("Fold %d: only %d labeled samples; copying raw", fold + 1, len(train_labeled))
            df.loc[val_df.index, cal_col] = val_df[raw_col].values
            continue

        # Fit one Platt scaler per model found in training fold
        model_platts: Dict[str, LogisticRegression] = {}
        for model_name, group in train_labeled.groupby(model_col):
            if len(group) < 5:
                continue
            platt = _fit_platt(group[raw_col].values, group["label"].values)
            if platt:
                model_platts[model_name] = platt

        # Apply to validation fold
        for model_name, group in val_df.groupby(model_col):
            platt = model_platts.get(model_name)
            if platt:
                vals = group[raw_col].values.reshape(-1, 1)
                calibrated = platt.predict_proba(vals)[:, 1]
                df.loc[group.index, cal_col] = calibrated
            else:
                # Fallback: use global Platt if model not seen
                global_platt = _fit_platt(train_labeled[raw_col].values, train_labeled["label"].values)
                if global_platt:
                    vals = group[raw_col].values.reshape(-1, 1)
                    df.loc[group.index, cal_col] = global_platt.predict_proba(vals)[:, 1]
                else:
                    df.loc[group.index, cal_col] = group[raw_col].values

    # Fallback for earliest fold (pure training)
    df[cal_col] = df[cal_col].fillna(df[raw_col])
    df[cal_col] = df[cal_col].clip(0.0, 1.0)
    df = df.drop(columns=["_idx"], errors="ignore")
    return df


# ------------------------------------------------------------------------------
# Full pipeline
# ------------------------------------------------------------------------------
def run_pipeline(n_splits: int = 5) -> pd.DataFrame:
    logger.info("=== Stage 1: Fetching production-suite decisions ===")
    raw_df = fetch_decisions_with_outcomes()
    if raw_df.empty:
        logger.error("No production-suite decisions found in DB.")
        return pd.DataFrame()

    logger.info("=== Stage 2: Engineering features ===")
    records = []
    for _, row in raw_df.iterrows():
        opinions = _safe_dict(row.get("analyst_opinions"))
        lead_conf = float(row.get("lead_confidence", 0.0) or 0.0)
        verdict = str(row.get("verifier_verdict", "SKIPPED")).upper()
        verifier_conf = float(row.get("verifier_confidence", 0.0) or 0.0)

        feats = _extract_all_features(opinions, lead_conf, verdict, verifier_conf)

        rec = {
            "decision_id": row["decision_id"],
            "timestamp": row["timestamp"],
            "symbol": row["symbol"],
            "trade_id": row["trade_id"],
            "label": 1.0 if row.get("pnl", 0) and row["pnl"] > 0 else 0.0,
            "pnl": row.get("pnl"),
            "lead_model": row.get("lead_model"),
            "verifier_model": row.get("verifier_model"),
            "tech_model": _extract_model(opinions, "technical"),
            "fund_model": _extract_model(opinions, "fundamental"),
            "sent_model": _extract_model(opinions, "sentiment"),
            "macro_model": _extract_model(opinions, "macro"),
            "lead_confidence": float(row.get("lead_confidence") or 0.0),
        }
        rec.update(feats)
        records.append(rec)

    df = pd.DataFrame(records)
    n_trades = len(df)
    n_wins = (df["label"] == 1.0).sum()
    logger.info("Labeled trades: %d (wins=%d, win_rate=%.1f%%)", n_trades, n_wins, 100 * n_wins / max(n_trades, 1))

    logger.info("=== Stage 3: Model-specific Platt calibration ===")
    # Calibrate tech, lead, sentiment — each by their respective model name
    df = calibrate_model_specific(df, "technical_conf", "feat_tech_prob_calibrated", "tech_model", n_splits)
    df = calibrate_model_specific(df, "sentiment_conf", "feat_sentiment_prob_calibrated", "sent_model", n_splits)
    df = calibrate_model_specific(df, "lead_confidence", "feat_lead_prob_calibrated", "lead_model", n_splits)

    # --- Interaction features (use calibrated probabilities) ---
    df["feat_interaction_lead_verifier"] = df["feat_lead_prob_calibrated"] * df["feat_verifier_score"]

    # Final feature columns for XGBoost
    feature_cols = [
        # Per-domain raw + calibrated
        "technical_conf", "feat_tech_prob_calibrated",
        "fundamental_conf", "feat_fund_conviction",
        "sentiment_conf", "feat_sentiment_prob_calibrated",
        "macro_conf", "feat_macro_conviction",
        "lead_confidence", "feat_lead_prob_calibrated",
        # Aggregate confidence
        "avg_confidence", "min_confidence", "max_confidence", "conf_std",
        # Bias agreement
        "bullish_count", "bearish_count", "neutral_count",
        "bias_agreement", "bias_majority",
        # Risk
        "total_risk_warnings", "any_risk",
        # Model diversity
        "unique_models", "model_count",
        # Verifier
        "verifier_approve", "verifier_revise", "verifier_veto", "verifier_skipped",
        "feat_verifier_score",
        # Interactions
        "feat_lead_verifier_raw", "feat_interaction_lead_verifier",
        # Disagreement
        "tech_fund_disagree",
    ]

    # Ensure all columns exist
    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0

    logger.info("=== Pipeline complete ===")
    logger.info("Trainable samples: %d | Features: %d", len(df), len(feature_cols))
    return df


def _extract_model(opinions, domain: str) -> str:
    opinions = _safe_dict(opinions)
    op = opinions.get(domain, {})
    return str(op.get("model_used", "unknown")) if isinstance(op, dict) else "unknown"


if __name__ == "__main__":
    df = run_pipeline()
    if df.empty:
        logger.error("No data produced. Exiting.")
        exit(1)
    out_path = "/app/data/meta_features.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    logger.info("Saved feature matrix to %s (%d rows)", out_path, len(df))

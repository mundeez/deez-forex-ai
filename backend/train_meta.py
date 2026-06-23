"""train_meta.py — Time-series cross-validated XGBoost meta-classifier training.

Trains an XGBoost classifier on calibrated LLM features to predict trade success.
Uses TimeSeriesSplit to avoid look-ahead bias and prints per-fold AUC.

Usage:
    docker compose exec -T backend python3 /app/train_meta.py
"""
import os
import json
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, f1_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_meta")

# Lazy import xgboost to avoid import overhead when just parsing args
_xgb = None


def _get_xgb():
    global _xgb
    if _xgb is None:
        import xgboost as xgb
        _xgb = xgb
    return _xgb


FEATURE_COLS = [
    "feat_tech_prob_calibrated",
    "feat_lead_prob_calibrated",
    "feat_fund_conviction",
    "feat_macro_conviction",
    "feat_sentiment_prob_calibrated",
    "feat_verifier_score",
    "feat_interaction_lead_verifier",
]


def load_feature_matrix(path: str = "/app/data/meta_features.csv") -> pd.DataFrame:
    """Load pre-computed feature matrix from pipeline.py."""
    if not os.path.exists(path):
        logger.info("Feature matrix not found at %s; running pipeline first...", path)
        from pipeline import run_pipeline
        df = run_pipeline()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_csv(path, index=False)
        return df
    df = pd.read_csv(path)
    logger.info("Loaded feature matrix: %d rows", len(df))
    return df


def evaluate_fold(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    y_pred: np.ndarray,
    fold_idx: int,
) -> Dict[str, float]:
    """Compute classification metrics for a single fold."""
    try:
        auc = roc_auc_score(y_true, y_proba)
    except ValueError:
        auc = 0.5

    metrics = {
        "fold": fold_idx,
        "samples": len(y_true),
        "positive_rate": float(y_true.mean()),
        "auc": float(auc),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    return metrics


def train_and_evaluate(
    df: pd.DataFrame,
    n_splits: int = 5,
    early_stopping_rounds: int = 15,
    model_path: str = "/app/models/meta_model_ts_cv.json",
) -> List[Dict[str, Any]]:
    """Time-series cross-validation with XGBoost native API.

    Uses xgb.train with DMatrix to work around XGBClassifier.fit() API issues.
    """
    xgb = _get_xgb()

    # Ensure correct dtypes
    df = df.copy()
    df["label"] = df["label"].astype(int)
    for col in FEATURE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Sort by timestamp to respect temporal order
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").reset_index(drop=True)

    X = df[FEATURE_COLS].values
    y = df["label"].values

    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics = []
    best_model = None
    best_auc = 0.0

    logger.info("=== Starting %d-fold time-series cross-validation ===", n_splits)
    logger.info("Total samples: %d | Features: %d | Positive rate: %.2f%%", len(y), X.shape[1], 100 * y.mean())

    base_params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 3,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "alpha": 1.0,
        "lambda": 1.0,
        "seed": 42,
        "nthread": 2,
    }

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]

        pos = y_train.sum()
        neg = len(y_train) - pos
        scale_pos_weight = max(1.0, neg / max(pos, 1))

        logger.info(
            "Fold %d | train=%d (pos=%d) | val=%d (pos=%d)",
            fold + 1, len(y_train), pos, len(y_val), y_val.sum()
        )

        params = {**base_params, "scale_pos_weight": scale_pos_weight}
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLS)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLS)

        evals = [(dtrain, "train"), (dval, "eval")]
        bst = xgb.train(
            params,
            dtrain,
            num_boost_round=500,
            evals=evals,
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False,
        )

        y_proba = bst.predict(dval)
        y_pred = (y_proba >= 0.5).astype(int)

        metrics = evaluate_fold(y_val, y_proba, y_pred, fold + 1)
        metrics["best_iteration"] = int(bst.best_iteration) if hasattr(bst, "best_iteration") else bst.num_boost_round()
        fold_metrics.append(metrics)

        logger.info(
            "Fold %d | AUC=%.4f | Acc=%.4f | F1=%.4f | best_iter=%s",
            metrics["fold"],
            metrics["auc"],
            metrics["accuracy"],
            metrics["f1"],
            metrics["best_iteration"],
        )

        if metrics["auc"] > best_auc:
            best_auc = metrics["auc"]
            best_model = bst

    # Train final model on ALL data
    logger.info("=== Training final model on full dataset ===")
    final_params = {**base_params, "scale_pos_weight": max(1.0, (len(y) - y.sum()) / max(y.sum(), 1))}
    dfull = xgb.DMatrix(X, label=y, feature_names=FEATURE_COLS)
    final_bst = xgb.train(final_params, dfull, num_boost_round=200, verbose_eval=False)

    # Feature importance
    importance = final_bst.get_score(importance_type="gain")
    sorted_imp = sorted(importance.items(), key=lambda kv: kv[1], reverse=True)
    logger.info("Feature importance (gain):")
    for feat, gain in sorted_imp:
        # XGBoost may use actual feature names if provided to DMatrix
        if feat.startswith("f") and feat[1:].isdigit():
            name = FEATURE_COLS[int(feat[1:])]
        else:
            name = feat
        logger.info("  %-40s gain=%.2f", name, gain)

    # Save model
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    final_bst.save_model(model_path)
    logger.info("Saved final model to %s", model_path)

    # Save metadata
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": int(len(y)),
        "n_features": int(X.shape[1]),
        "feature_names": FEATURE_COLS,
        "positive_rate": float(y.mean()),
        "fold_metrics": fold_metrics,
        "mean_auc": float(np.mean([m["auc"] for m in fold_metrics])),
        "std_auc": float(np.std([m["auc"] for m in fold_metrics])),
        "best_fold_auc": float(best_auc),
        "feature_importance": {
            (FEATURE_COLS[int(k.replace("f", ""))] if k.startswith("f") and k[1:].isdigit() else k): float(v)
            for k, v in importance.items()
        },
    }
    meta_path = model_path.replace(".json", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Saved metadata to %s", meta_path)

    return fold_metrics, final_bst, meta


def print_summary(fold_metrics: List[Dict[str, Any]], meta: Dict[str, Any]):
    """Pretty-print the cross-validation summary."""
    print("\n" + "=" * 60)
    print("  META-CLASSIFIER CROSS-VALIDATION SUMMARY")
    print("=" * 60)
    print(f"  {'Fold':>6} | {'AUC':>8} | {'Acc':>8} | {'F1':>8} | {'PosRate':>8}")
    print("-" * 60)
    for m in fold_metrics:
        print(
            f"  {m['fold']:>6} | {m['auc']:>8.4f} | {m['accuracy']:>8.4f} | "
            f"{m['f1']:>8.4f} | {m['positive_rate']:>8.2%}"
        )
    print("-" * 60)
    print(f"  {'Mean':>6} | {meta['mean_auc']:>8.4f}")
    print(f"  {'Std':>6}  | {meta['std_auc']:>8.4f}")
    print(f"  {'Best':>6} | {meta['best_fold_auc']:>8.4f}")
    print("=" * 60)
    print(f"  Total samples: {meta['n_samples']}")
    print(f"  Baseline AUC  : 0.5000 (random)")
    print(f"  Baseline Acc  : {max(meta['positive_rate'], 1 - meta['positive_rate']):.4f} (majority class)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    df = load_feature_matrix()
    if len(df) == 0:
        logger.error("No data loaded. Exiting.")
        exit(1)

    fold_metrics, final_model, meta = train_and_evaluate(df, n_splits=5)
    print_summary(fold_metrics, meta)

"""v2 AI Team Meta-Model.

Trains a meta-classifier that predicts trade success based on:
  1. Per-analyst model performance (which analyst models correlate with wins)
  2. Analyst opinion patterns (confidence, bias agreement, risk warnings)
  3. Verifier verdict patterns

This sits on top of the individual analyst models and learns which
combinations of analyst opinions predict profitable trades.
"""
import logging
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.services.ml.team_meta")

_xgb = None
_jb = None


def _lazy_imports():
    global _xgb, _jb
    if _xgb is None:
        import xgboost as xgb
        _xgb = xgb
    if _jb is None:
        import joblib
        _jb = joblib
    return _xgb, _jb


def _extract_analyst_features(opinions: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Extract flat features from analyst_opinions JSON."""
    if not opinions:
        return {}

    features = {}
    domains = ["technical", "fundamental", "sentiment", "macro"]
    confidences = []
    biases = []
    risk_warnings = 0
    model_names = []

    for domain in domains:
        op = opinions.get(domain, {})
        conf = op.get("confidence_score", 0.0)
        confidences.append(float(conf) if conf else 0.0)
        features[f"{domain}_conf"] = float(conf) if conf else 0.0

        bias = op.get("bias", "NEUTRAL")
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

    # Aggregate features
    features["avg_confidence"] = np.mean(confidences) if confidences else 0.0
    features["min_confidence"] = np.min(confidences) if confidences else 0.0
    features["max_confidence"] = np.max(confidences) if confidences else 0.0
    features["conf_std"] = np.std(confidences) if len(confidences) > 1 else 0.0

    # Bias agreement
    bullish_count = sum(1 for b in biases if b == "BULLISH")
    bearish_count = sum(1 for b in biases if b == "BEARISH")
    neutral_count = sum(1 for b in biases if b == "NEUTRAL")
    features["bullish_count"] = bullish_count
    features["bearish_count"] = bearish_count
    features["neutral_count"] = neutral_count
    features["bias_agreement"] = max(bullish_count, bearish_count, neutral_count) / len(domains)
    features["bias_majority"] = 1.0 if max(bullish_count, bearish_count) >= 3 else 0.0

    # Risk
    features["total_risk_warnings"] = risk_warnings
    features["any_risk"] = 1.0 if risk_warnings > 0 else 0.0

    # Model diversity
    features["unique_models"] = len(set(model_names))
    features["model_count"] = len(model_names)

    return features


def _extract_verifier_features(verdict: Optional[str], lead_model: Optional[str]) -> Dict[str, float]:
    features = {
        "verifier_approve": 1.0 if verdict == "APPROVE" else 0.0,
        "verifier_revise": 1.0 if verdict == "REVISE" else 0.0,
        "verifier_veto": 1.0 if verdict == "VETO" else 0.0,
        "verifier_skipped": 1.0 if verdict in (None, "SKIPPED") else 0.0,
        "lead_is_nemotron": 1.0 if lead_model and "nemotron" in lead_model.lower() else 0.0,
        "lead_is_gptoss": 1.0 if lead_model and "gpt-oss" in lead_model.lower() else 0.0,
    }
    return features


class TeamMetaModel:
    """Meta-classifier for v2 AI team decisions."""

    MODEL_PATH = "/app/models/team_meta_model.pkl"
    REDIS_KEY = "ml:team_meta:version"

    def __init__(self):
        self.model = None
        self.feature_cols = []
        self.version = None
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not os.path.exists(self.MODEL_PATH):
            return
        try:
            _, joblib = _lazy_imports()
            artifact = joblib.load(self.MODEL_PATH)
            self.model = artifact["model"]
            self.feature_cols = artifact.get("feature_cols", [])
            self.version = artifact.get("version")
            logger.info("Loaded TeamMetaModel from %s", self.MODEL_PATH)
        except Exception:
            logger.warning("Failed to load team meta model", exc_info=True)

    def _build_feature_vector(self, analyst_opinions, verifier_verdict, lead_model) -> Dict[str, float]:
        feats = {}
        feats.update(_extract_analyst_features(analyst_opinions))
        feats.update(_extract_verifier_features(verdict=verifier_verdict, lead_model=lead_model))
        return feats

    def train(self, df: pd.DataFrame, label_col: str = "label", test_size: float = 0.2, seed: int = 42) -> Dict[str, Any]:
        xgb, joblib = _lazy_imports()

        drop_cols = [label_col, "symbol", "direction"]
        feature_cols = [c for c in df.columns if c not in drop_cols]
        X = df[feature_cols].copy()
        y = df[label_col].copy()
        X = X.fillna(X.median())

        # Time-based split
        split_idx = int(len(X) * (1 - test_size))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        pos = (y_train == 1).sum()
        neg = (y_train == 0).sum()
        scale_pos_weight = max(1.0, neg / max(pos, 1))

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            scale_pos_weight=scale_pos_weight,
            eval_metric="auc",
            use_label_encoder=False,
            random_state=seed,
            n_jobs=2,
        )

        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

        train_pred = model.predict_proba(X_train)[:, 1]
        test_pred = model.predict_proba(X_test)[:, 1]

        from sklearn.metrics import roc_auc_score
        train_auc = roc_auc_score(y_train, train_pred)
        test_auc = roc_auc_score(y_test, test_pred) if len(set(y_test)) > 1 else 0.5

        metrics = {
            "train_auc": float(train_auc),
            "test_auc": float(test_auc),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_rate": float(y.mean()),
            "feature_count": len(feature_cols),
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }

        os.makedirs(os.path.dirname(self.MODEL_PATH), exist_ok=True)
        joblib.dump({"model": model, "feature_cols": feature_cols, "version": metrics["trained_at"]}, self.MODEL_PATH)

        self.model = model
        self.feature_cols = feature_cols
        self.version = metrics["trained_at"]

        # Sync Redis cache
        try:
            import redis
            from app.config import get_settings
            r = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
            r.set(self.REDIS_KEY, json.dumps(metrics))
            r.close()
        except Exception:
            logger.warning("Failed to cache team meta model version")

        logger.info("TeamMetaModel trained — train_auc=%.3f test_auc=%.3f", train_auc, test_auc)
        return metrics

    def predict(self, analyst_opinions, verifier_verdict, lead_model) -> Optional[float]:
        if self.model is None:
            return None
        feats = self._build_feature_vector(analyst_opinions, verifier_verdict, lead_model)
        row = pd.DataFrame([{k: feats.get(k, 0.0) for k in self.feature_cols}])
        row = row.fillna(0.0)
        proba = self.model.predict_proba(row)[:, 1]
        return float(proba[0])

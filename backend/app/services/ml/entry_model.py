"""XGBoost Entry Quality Classifier.

Predicts the probability that a given trade entry will be profitable.
Trained on historical decisions with labels (profitable=1, loss=0).

Model artifact is stored via joblib and version-tracked in Redis.
"""
import logging
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.services.feature_store import FeatureStore

logger = logging.getLogger("app.services.ml.entry_model")

# Lazy imports — only loaded when training/inference actually runs
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


class EntryQualityModel:
    """XGBoost binary classifier for entry quality."""

    MODEL_PATH = "/app/models/xgb_entry_model.pkl"
    REDIS_KEY = "ml:entry_model:version"
    FEATURE_COLS = None  # Set at training time

    def __init__(self):
        self.model = None
        self.feature_cols = []
        self.version = None
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        df: pd.DataFrame,
        label_col: str = "label",
        test_size: float = 0.2,
        seed: int = 42,
    ) -> Dict[str, Any]:
        """Train the XGBoost classifier and return evaluation metrics."""
        xgb, joblib = _lazy_imports()

        # Drop non-feature columns
        drop_cols = [label_col, "symbol", "direction"]
        feature_cols = [c for c in df.columns if c not in drop_cols]
        X = df[feature_cols].copy()
        y = df[label_col].copy()

        # Handle any remaining NaNs
        X = X.fillna(X.median())

        # Time-based split: last 20% as OOS
        split_idx = int(len(X) * (1 - test_size))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

        # Scale-Pos-Weight for imbalanced data
        pos = (y_train == 1).sum()
        neg = (y_train == 0).sum()
        scale_pos_weight = max(1.0, neg / max(pos, 1))

        model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            eval_metric="auc",
            use_label_encoder=False,
            random_state=seed,
            n_jobs=2,
        )

        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        # Evaluate
        train_pred = model.predict_proba(X_train)[:, 1]
        test_pred = model.predict_proba(X_test)[:, 1]

        metrics = {
            "train_auc": float(self._auc(y_train, train_pred)),
            "test_auc": float(self._auc(y_test, test_pred)),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_rate": float(y.mean()),
            "feature_count": len(feature_cols),
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist
        os.makedirs(os.path.dirname(self.MODEL_PATH), exist_ok=True)
        joblib.dump({"model": model, "feature_cols": feature_cols}, self.MODEL_PATH)

        self.model = model
        self.feature_cols = feature_cols
        self.version = metrics["trained_at"]
        self._cache_version(metrics)

        logger.info(
            "EntryQualityModel trained — train_auc=%.3f test_auc=%.3f n=%d",
            metrics["train_auc"], metrics["test_auc"], len(X),
        )
        return metrics

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, features: Dict[str, float]) -> Optional[float]:
        """Return probability [0,1] that this entry is profitable.

        Returns None if no model is loaded.
        """
        if self.model is None:
            return None

        row = pd.DataFrame([{k: features.get(k, 0.0) for k in self.feature_cols}])
        row = row.fillna(0.0)
        proba = self.model.predict_proba(row)[:, 1]
        return float(proba[0])

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> None:
        if not os.path.exists(self.MODEL_PATH):
            return
        try:
            _, joblib = _lazy_imports()
            artifact = joblib.load(self.MODEL_PATH)
            self.model = artifact["model"]
            self.feature_cols = artifact.get("feature_cols", [])
            self.version = artifact.get("version")
            logger.info("Loaded EntryQualityModel from %s", self.MODEL_PATH)
        except Exception:
            logger.warning("Failed to load entry model from disk", exc_info=True)

    def _cache_version(self, metrics: Dict[str, Any]) -> None:
        try:
            import redis
            from app.config import get_settings
            r = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
            payload = json.dumps(metrics)
            r.set(self.REDIS_KEY, payload)
            r.close()
        except Exception:
            logger.warning("Failed to cache model version in Redis", exc_info=True)

    @staticmethod
    def _auc(y_true: pd.Series, y_score: np.ndarray) -> float:
        from sklearn.metrics import roc_auc_score
        try:
            return roc_auc_score(y_true, y_score)
        except ValueError:
            return 0.5

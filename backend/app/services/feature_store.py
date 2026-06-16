"""FeatureStore — compute entry-time features for ML models.

Extracts structured features from the market snapshot at decision time
for use in supervised learning (entry quality, exit optimization, etc.).
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import pandas as pd
import numpy as np

logger = logging.getLogger("app.services.feature_store")


class FeatureStore:
    """Compute feature vectors from analysis snapshots and market data."""

    @staticmethod
    def compute_entry_features(analysis: Dict[str, Any]) -> Dict[str, float]:
        """Extract a flat feature dict from an analysis snapshot at entry time.

        Returns ~30 numeric features suitable for XGBoost.
        """
        features = {}

        # Technical features
        tech = analysis.get("technical", {})
        tfs = tech.get("timeframes", {})
        
        # Use the finest timeframe available (1m for scalping, 5m for day, 1h for swing)
        tf_keys = ["1m", "5m", "15m", "1h", "4h", "1d"]
        primary_tf = None
        for k in tf_keys:
            if k in tfs:
                primary_tf = tfs[k]
                break

        if primary_tf:
            ind = primary_tf.get("indicators", {})
            features["rsi_14"] = _safe_float(ind.get("rsi_14"), 50.0)
            features["macd"] = _safe_float(ind.get("macd"), 0.0)
            features["macd_hist"] = _safe_float(ind.get("macd_hist"), 0.0)
            features["adx_14"] = _safe_float(ind.get("adx_14"), 20.0)
            features["atr_14"] = _safe_float(ind.get("atr_14"), 0.0)
            features["bb_upper_dist"] = _dist_pct(ind.get("bb_upper"), ind.get("close"))
            features["bb_lower_dist"] = _dist_pct(ind.get("bb_lower"), ind.get("close"))
            features["vwap_dist"] = _dist_pct(ind.get("vwap"), ind.get("close"))
            features["ema9_dist"] = _dist_pct(ind.get("ema_9"), ind.get("close"))
            features["ema21_dist"] = _dist_pct(ind.get("ema_21"), ind.get("close"))
            features["stoch_k"] = _safe_float(ind.get("stoch_k"), 50.0)
            features["stoch_d"] = _safe_float(ind.get("stoch_d"), 50.0)
            features["cci_20"] = _safe_float(ind.get("cci_20"), 0.0)
            features["bb_squeeze"] = 1.0 if primary_tf.get("bb_squeeze") else 0.0
            
            # Divergence feature
            div = primary_tf.get("divergence", "none")
            features["bullish_div"] = 1.0 if div == "bullish_divergence" else 0.0
            features["bearish_div"] = 1.0 if div == "bearish_divergence" else 0.0

        # Fundamental features
        fund = analysis.get("fundamental", {})
        features["event_risk"] = _risk_level(fund.get("event_risk", "low"))
        features["high_impact_events"] = float(fund.get("high_impact_events", 0))
        features["rate_spread"] = _safe_float(fund.get("interest_rate_spread"), 0.0)
        features["surprise_index"] = _safe_float(fund.get("economic_surprise_index"), 0.0)

        # Sentiment features
        sent = analysis.get("sentiment", {})
        features["sentiment_score"] = _safe_float(sent.get("sentiment_score"), 0.0)
        retail = sent.get("retail", {})
        features["retail_long_pct"] = _safe_float(retail.get("long_pct"), 50.0)
        inst = sent.get("institutional", {})
        features["cot_net"] = _safe_float(inst.get("net_position"), 0.0) / 1000.0
        features["cot_bias_bull"] = 1.0 if inst.get("institutional_bias") == "bullish" else 0.0
        features["cot_bias_bear"] = 1.0 if inst.get("institutional_bias") == "bearish" else 0.0

        # Macro features
        macro = analysis.get("macro", {})
        features["dxy"] = _safe_float(macro.get("dxy"), 100.0)
        features["vix"] = _safe_float(macro.get("vix"), 20.0)
        features["yield_spread"] = _safe_float(macro.get("yield_spread_10y_2y"), 0.0)
        features["risk_on_score"] = _safe_float(macro.get("risk_on_score"), 0.0)
        features["macro_bias_risk_on"] = 1.0 if macro.get("bias") == "risk_on" else 0.0
        features["macro_bias_risk_off"] = 1.0 if macro.get("bias") == "risk_off" else 0.0

        # Time features
        now = datetime.now(timezone.utc)
        features["hour_sin"] = np.sin(2 * np.pi * now.hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * now.hour / 24)
        features["day_of_week"] = float(now.weekday())

        # Cross-sectional signal agreement
        overall_signal = tech.get("overall_signal", "neutral")
        features["signal_bullish"] = 1.0 if overall_signal == "bullish" else 0.0
        features["signal_bearish"] = 1.0 if overall_signal == "bearish" else 0.0

        # Confidence
        if primary_tf:
            features["technical_confidence"] = _safe_float(primary_tf.get("confidence"), 0.5)
        else:
            features["technical_confidence"] = 0.5

        return features

    @staticmethod
    def export_training_set(
        decisions: List[Dict[str, Any]],
    ) -> pd.DataFrame:
        """Build a training DataFrame from a list of decisions with outcomes.

        Each decision must have:
          - 'features': dict from compute_entry_features()
          - 'label': 1 for profitable trade, 0 for losing trade
        """
        rows = []
        for d in decisions:
            feats = d.get("features", {})
            row = dict(feats)
            row["label"] = d.get("label", 0)
            row["symbol"] = d.get("symbol", "EURUSD")
            row["direction"] = 1 if d.get("direction") == "buy" else 0
            rows.append(row)
        return pd.DataFrame(rows)


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _risk_level(level: str) -> float:
    mapping = {"low": 0.0, "medium": 1.0, "high": 2.0}
    return mapping.get(level.lower(), 0.0)


def _dist_pct(band: Optional[float], close: Optional[float]) -> float:
    """Distance from price to band as % of price."""
    if band is None or close is None or close == 0:
        return 0.0
    try:
        return (float(band) - float(close)) / float(close) * 100.0
    except (ValueError, TypeError):
        return 0.0

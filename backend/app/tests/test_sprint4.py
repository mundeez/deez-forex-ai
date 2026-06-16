"""Sprint 4 unit tests — Supervised Learning Pipeline."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd

from app.services.feature_store import FeatureStore
from app.services.pattern_extractor import PatternExtractor
from app.services.analyst_weight_optimizer import AnalystWeightOptimizer


class TestFeatureStore:
    def test_compute_entry_features_structure(self):
        analysis = {
            "technical": {
                "timeframes": {
                    "1m": {
                        "signal": "bullish",
                        "confidence": 0.75,
                        "indicators": {
                            "rsi_14": 65.0,
                            "macd": 0.0005,
                            "macd_hist": 0.0002,
                            "adx_14": 28.0,
                            "atr_14": 0.0010,
                            "bb_upper": 1.0850,
                            "bb_lower": 1.0750,
                            "vwap": 1.0800,
                            "ema_9": 1.0810,
                            "ema_21": 1.0805,
                            "stoch_k": 55.0,
                            "stoch_d": 52.0,
                            "cci_20": 45.0,
                            "close": 1.0800,
                        },
                        "bb_squeeze": False,
                        "divergence": "none",
                    }
                },
                "overall_signal": "bullish",
            },
            "fundamental": {
                "event_risk": "medium",
                "high_impact_events": 1,
                "interest_rate_spread": 1.25,
                "economic_surprise_index": 0.3,
            },
            "sentiment": {
                "sentiment_score": 0.4,
                "retail": {"long_pct": 60.0, "short_pct": 40.0},
                "institutional": {
                    "net_position": 15000,
                    "institutional_bias": "bullish",
                },
            },
            "macro": {
                "dxy": 103.5,
                "vix": 18.0,
                "yield_spread_10y_2y": 0.8,
                "risk_on_score": 0.2,
                "bias": "risk_on",
            },
        }
        feats = FeatureStore.compute_entry_features(analysis)
        assert "rsi_14" in feats
        assert "macd" in feats
        assert "adx_14" in feats
        assert "stoch_k" in feats
        assert "cci_20" in feats
        assert "dxy" in feats
        assert "vix" in feats
        assert "risk_on_score" in feats
        assert "hour_sin" in feats
        assert "hour_cos" in feats
        assert feats["signal_bullish"] == 1.0
        assert feats["signal_bearish"] == 0.0
        assert feats["bb_squeeze"] == 0.0

    def test_export_training_set(self):
        decisions = [
            {
                "features": {"rsi_14": 60.0, "macd": 0.001},
                "label": 1,
                "symbol": "EURUSD",
                "direction": "buy",
            },
            {
                "features": {"rsi_14": 30.0, "macd": -0.001},
                "label": 0,
                "symbol": "EURUSD",
                "direction": "sell",
            },
        ]
        df = FeatureStore.export_training_set(decisions)
        assert len(df) == 2
        assert "label" in df.columns
        assert df["label"].iloc[0] == 1
        assert df["label"].iloc[1] == 0


class TestPatternExtractor:
    def test_compute_pattern_priors(self):
        trades = [
            {"symbol": "EURUSD", "direction": "buy", "pnl": 100, "regime": "trending", "session": "london", "pattern_tags": ["ema_cross"]},
            {"symbol": "EURUSD", "direction": "buy", "pnl": -50, "regime": "trending", "session": "london", "pattern_tags": ["ema_cross"]},
            {"symbol": "EURUSD", "direction": "sell", "pnl": 80, "regime": "ranging", "session": "ny", "pattern_tags": ["bb_bounce"]},
            {"symbol": "GBPUSD", "direction": "buy", "pnl": 120, "regime": "trending", "session": "london", "pattern_tags": ["ema_cross", "momentum"]},
        ]
        priors = PatternExtractor.compute_pattern_priors(trades)
        assert priors["total_trades"] == 4
        assert priors["overall_win_rate"] == 0.75
        assert "by_regime" in priors
        assert "by_session" in priors
        assert "by_pattern_tag" in priors
        # ema_cross: 3 trades (2 wins: EURUSD +100, GBPUSD +120; 1 loss: EURUSD -50) -> 0.667 wr
        assert priors["by_pattern_tag"]["ema_cross"]["win_rate"] == 0.667
        # bb_bounce: 1 trade, 1 win -> 1.0 wr
        assert priors["by_pattern_tag"]["bb_bounce"]["win_rate"] == 1.0

    def test_empty_trades(self):
        priors = PatternExtractor.compute_pattern_priors([])
        assert priors == {}


class TestAnalystWeightOptimizer:
    def test_compute_weights(self):
        decisions = [
            {"regime": "trending", "session": "london", "analyst_signals": {"technical": "bullish", "fundamental": "bullish", "sentiment": "bearish", "macro": "neutral"}, "outcome": 1},
            {"regime": "trending", "session": "london", "analyst_signals": {"technical": "bullish", "fundamental": "bullish", "sentiment": "bullish", "macro": "neutral"}, "outcome": 1},
            {"regime": "trending", "session": "london", "analyst_signals": {"technical": "bearish", "fundamental": "bullish", "sentiment": "bearish", "macro": "neutral"}, "outcome": 0},
            {"regime": "ranging", "session": "ny", "analyst_signals": {"technical": "bearish", "fundamental": "bearish", "sentiment": "bullish", "macro": "neutral"}, "outcome": 1},
        ]
        weights = AnalystWeightOptimizer.compute_weights(decisions)
        assert "by_regime" in weights
        assert "by_session" in weights
        assert "default" in weights
        # trending regime: technical bullish twice correct, once wrong -> high weight
        trending = weights["by_regime"]["trending"]
        assert trending["technical"] > 0.2

    def test_get_weights_for_context(self):
        weights_dict = {
            "by_regime": {
                "trending": {"technical": 0.5, "fundamental": 0.2, "sentiment": 0.2, "macro": 0.1},
            },
            "by_session": {
                "london": {"technical": 0.4, "fundamental": 0.3, "sentiment": 0.2, "macro": 0.1},
            },
            "default": {"technical": 0.25, "fundamental": 0.25, "sentiment": 0.25, "macro": 0.25},
        }
        # Regime match
        w = AnalystWeightOptimizer.get_weights_for_context(weights_dict, regime="trending", session="ny")
        assert w["technical"] == 0.5
        # Session fallback
        w = AnalystWeightOptimizer.get_weights_for_context(weights_dict, regime="unknown", session="london")
        assert w["technical"] == 0.4
        # Default fallback
        w = AnalystWeightOptimizer.get_weights_for_context(weights_dict, regime="unknown", session="unknown")
        assert w["technical"] == 0.25

    def test_weights_differ_between_regimes(self):
        """Acceptance: analyst weights differ between trending and ranging."""
        decisions = [
            {"regime": "trending", "session": "london", "analyst_signals": {"technical": "bullish", "fundamental": "bullish", "sentiment": "bearish", "macro": "neutral"}, "outcome": 1},
            {"regime": "trending", "session": "london", "analyst_signals": {"technical": "bullish", "fundamental": "bearish", "sentiment": "bearish", "macro": "neutral"}, "outcome": 1},
            {"regime": "ranging", "session": "london", "analyst_signals": {"technical": "bullish", "fundamental": "bearish", "sentiment": "bullish", "macro": "neutral"}, "outcome": 0},
            {"regime": "ranging", "session": "london", "analyst_signals": {"technical": "bearish", "fundamental": "bullish", "sentiment": "bullish", "macro": "neutral"}, "outcome": 1},
        ]
        weights = AnalystWeightOptimizer.compute_weights(decisions)
        trending = weights["by_regime"]["trending"]
        ranging = weights["by_regime"]["ranging"]
        assert trending != ranging

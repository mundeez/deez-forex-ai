"""Market regime detector.

Classifies the current market state per symbol/timeframe into one of:
  trending, ranging, breakout, reversal, unknown

Uses ADX, Bollinger Band width, ATR, and price structure.
"""
import logging
from typing import Dict, Any, Optional

from app.services.instruments import pip_size

logger = logging.getLogger("app.services.regime_detector")


class RegimeDetector:
    """Detect market regime from technical indicator snapshot."""

    @staticmethod
    def detect(
        technical: Dict[str, Any],
        symbol: str = "EURUSD",
    ) -> Dict[str, Any]:
        """Return regime dict with label, confidence, and raw features."""
        tfs = technical.get("timeframes", {})
        # Prefer 1h, fallback to 4h, then 15m
        tf = tfs.get("1h") or tfs.get("4h") or tfs.get("15m") or {}
        ind = tf.get("indicators", {})

        adx = ind.get("adx_14", 0) or 0
        bb_upper = ind.get("bb_upper", 0) or 0
        bb_lower = ind.get("bb_lower", 0) or 0
        bb_mid = (bb_upper + bb_lower) / 2.0 if bb_upper and bb_lower else 0
        atr = ind.get("atr_14", 0) or 0
        close = ind.get("close", 0) or 0
        ema9 = ind.get("ema_9", 0) or 0
        ema21 = ind.get("ema_21", 0) or 0

        # Compute BB width as % of price
        bb_width_pct = 0.0
        if bb_upper and bb_lower and close and close > 0:
            bb_width_pct = (bb_upper - bb_lower) / close * 100

        # Compute ATR as % of price
        atr_pct = 0.0
        if atr and close and close > 0:
            atr_pct = atr / close * 100

        # Regime classification logic
        regime = "unknown"
        confidence = 0.0

        if adx >= 25:
            if bb_width_pct > 0.3:
                regime = "trending"
                confidence = min(adx / 50.0, 1.0)
            else:
                regime = "breakout"
                confidence = 0.7
        elif adx < 20:
            if bb_width_pct < 0.15:
                regime = "ranging"
                confidence = 1.0 - (adx / 25.0)
            else:
                regime = "unknown"
                confidence = 0.5
        else:  # 20 <= adx < 25
            # Check for reversal signals
            ema_cross = (ema9 > ema21) if ema9 and ema21 else False
            recent_signal = tf.get("signal", "neutral")
            if recent_signal in ("bullish_reversal", "bearish_reversal"):
                regime = "reversal"
                confidence = 0.6
            else:
                regime = "ranging"
                confidence = 0.5

        return {
            "regime": regime,
            "confidence": round(confidence, 2),
            "adx": round(adx, 2),
            "bb_width_pct": round(bb_width_pct, 4),
            "atr_pct": round(atr_pct, 4),
        }

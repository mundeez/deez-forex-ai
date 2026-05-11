import pandas as pd
import numpy as np
from typing import Dict, Any, List


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _bbands(series: pd.Series, length: int = 20, std: int = 2) -> tuple:
    middle = series.rolling(length).mean()
    sigma = series.rolling(length).std()
    upper = middle + std * sigma
    lower = middle - std * sigma
    return upper, middle, lower


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length).mean()


class TechnicalAnalyzer:
    def analyze(self, candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(candles) < 60:
            return {"signal": "neutral", "confidence": 0.0, "details": "Insufficient data"}

        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        close = df["close"]
        df["EMA_9"] = _ema(close, 9)
        df["EMA_21"] = _ema(close, 21)
        df["EMA_50"] = _ema(close, 50)
        df["EMA_200"] = _ema(close, 200)
        df["RSI_14"] = _rsi(close, 14)
        macd_line, signal_line, macd_hist = _macd(close)
        df["MACD"] = macd_line
        df["MACD_SIGNAL"] = signal_line
        df["MACD_HIST"] = macd_hist
        bb_upper, bb_middle, bb_lower = _bbands(close)
        df["BB_UPPER"] = bb_upper
        df["BB_MIDDLE"] = bb_middle
        df["BB_LOWER"] = bb_lower
        df["ATR_14"] = _atr(df, 14)

        last = df.iloc[-1]

        ema9 = last.get("EMA_9")
        ema21 = last.get("EMA_21")
        ema50 = last.get("EMA_50")
        ema200 = last.get("EMA_200")
        rsi = last.get("RSI_14")
        macd = last.get("MACD")
        macd_signal = last.get("MACD_SIGNAL")
        macd_hist = last.get("MACD_HIST")
        bb_upper_val = last.get("BB_UPPER")
        bb_lower_val = last.get("BB_LOWER")
        bb_middle_val = last.get("BB_MIDDLE")
        atr = last.get("ATR_14")
        close_price = last["close"]

        bullish_factors = 0
        bearish_factors = 0
        total_factors = 0

        if pd.notna(ema9) and pd.notna(ema21):
            total_factors += 1
            if ema9 > ema21:
                bullish_factors += 1
            else:
                bearish_factors += 1

        if pd.notna(ema50) and pd.notna(ema200):
            total_factors += 1
            if ema50 > ema200:
                bullish_factors += 1
            else:
                bearish_factors += 1

        if pd.notna(rsi):
            total_factors += 1
            if rsi < 30:
                bullish_factors += 1
            elif rsi > 70:
                bearish_factors += 1

        if pd.notna(macd) and pd.notna(macd_signal):
            total_factors += 1
            if macd > macd_signal:
                bullish_factors += 1
            else:
                bearish_factors += 1

        if pd.notna(bb_upper_val) and pd.notna(bb_lower_val):
            total_factors += 1
            if close_price <= bb_lower_val:
                bullish_factors += 1
            elif close_price >= bb_upper_val:
                bearish_factors += 1

        trend = "neutral"
        if bullish_factors > bearish_factors:
            trend = "bullish"
        elif bearish_factors > bullish_factors:
            trend = "bearish"

        confidence = 0.0
        if total_factors > 0:
            confidence = max(bullish_factors, bearish_factors) / total_factors

        support, resistance = self._find_support_resistance(df)
        divergence = self._detect_divergence(df)

        return {
            "signal": trend,
            "confidence": round(confidence, 2),
            "indicators": {
                "ema_9": round(ema9, 5) if pd.notna(ema9) else None,
                "ema_21": round(ema21, 5) if pd.notna(ema21) else None,
                "ema_50": round(ema50, 5) if pd.notna(ema50) else None,
                "ema_200": round(ema200, 5) if pd.notna(ema200) else None,
                "rsi_14": round(rsi, 2) if pd.notna(rsi) else None,
                "macd": round(macd, 5) if pd.notna(macd) else None,
                "macd_signal": round(macd_signal, 5) if pd.notna(macd_signal) else None,
                "macd_hist": round(macd_hist, 5) if pd.notna(macd_hist) else None,
                "bb_upper": round(bb_upper_val, 5) if pd.notna(bb_upper_val) else None,
                "bb_lower": round(bb_lower_val, 5) if pd.notna(bb_lower_val) else None,
                "bb_middle": round(bb_middle_val, 5) if pd.notna(bb_middle_val) else None,
                "atr_14": round(atr, 5) if pd.notna(atr) else None,
                "close": round(close_price, 5),
            },
            "support": support,
            "resistance": resistance,
            "divergence": divergence,
        }

    def _find_support_resistance(self, df: pd.DataFrame, lookback: int = 20) -> tuple:
        recent = df.tail(lookback)
        lows = recent["low"].tolist()
        highs = recent["high"].tolist()
        support = round(min(lows), 5) if lows else None
        resistance = round(max(highs), 5) if highs else None
        return support, resistance

    def _detect_divergence(self, df: pd.DataFrame) -> str:
        if len(df) < 5:
            return "none"
        last5 = df.tail(5)
        price_lows = last5["low"].tolist()
        rsi_vals = last5["RSI_14"].tolist()
        if price_lows[0] > price_lows[-1] and rsi_vals[0] < rsi_vals[-1]:
            return "bullish_divergence"
        price_highs = last5["high"].tolist()
        if price_highs[0] < price_highs[-1] and rsi_vals[0] > rsi_vals[-1]:
            return "bearish_divergence"
        return "none"

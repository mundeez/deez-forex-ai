import json
import logging

from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
from app.analysis.technical import TechnicalAnalyzer
from app.analysis.fundamental import FundamentalAnalyzer
from app.analysis.sentiment import SentimentAnalyzer
from app.analysis.macro import MacroAnalyzer
from app.config import get_settings
from app import schemas
from app.enums import DataProvider

settings = get_settings()
logger = logging.getLogger("app.analysis.aggregator")

# Redis TTLs for pre-computed snapshots
_TECH_SNAPSHOT_TTL = 1800   # 30 minutes — refreshed by refresh_technical_snapshots task
_SENTIMENT_CACHE_TTL = 7200  # 2 hours   — refreshed by refresh_sentiment_cache task


def _numpy_safe_default(obj):
    """JSON serialiser fallback that handles numpy scalar types."""
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


class AnalysisAggregator:
    def __init__(self, provider: schemas.DataProvider = None):
        self.provider = provider or settings.DATA_PROVIDER
        if self.provider == DataProvider.MT5_ZMQ:
            self.client = MT5ZMQClient()
        else:
            self.client = MetaApiClient()
        self.technical = TechnicalAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.sentiment = SentimentAnalyzer()
        self.macro = MacroAnalyzer()

    # ------------------------------------------------------------------
    # Redis cache helpers
    # ------------------------------------------------------------------

    async def _read_redis_json(self, key: str):
        """Return a cached JSON object from Redis, or None on miss / error."""
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            raw = await r.get(key)
            await r.close()
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Redis read miss for %s: %s", key, exc)
        return None

    async def _write_redis_json(self, key: str, value: dict, ttl: int) -> None:
        """Serialise and store a JSON object in Redis with TTL. Silently swallows errors."""
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.setex(key, ttl, json.dumps(value, default=_numpy_safe_default))
            await r.close()
        except Exception as exc:
            logger.debug("Redis write failed for %s: %s", key, exc)

    # ------------------------------------------------------------------
    # Main aggregation — cache-first for technical + sentiment
    # ------------------------------------------------------------------

    async def gather_all(
        self, symbol: str = "EURUSD", strategy_mode: str = "scalping", db = None, as_of = None
    ) -> dict:
        # --- Backtest mode: skip all Redis caches, query DB with as_of ---
        is_backtest = as_of is not None

        # --- Sentiment ---
        if is_backtest:
            sentiment = await self.sentiment.analyze(symbol, db=db, as_of=as_of)
        else:
            sentiment_key = f"sentiment_cache:{symbol}"
            sentiment = await self._read_redis_json(sentiment_key)
            if sentiment is None:
                logger.debug("Sentiment cache miss for %s — computing live", symbol)
                sentiment = await self.sentiment.analyze(symbol, db=db)
                await self._write_redis_json(sentiment_key, sentiment, _SENTIMENT_CACHE_TTL)

        # --- Technical ---
        if is_backtest:
            # In backtest mode, technical analysis is handled by the caller
            # (backtest engine loads historical candles directly). We skip
            # the live candle fetch and Redis cache here.
            technical = {}
        else:
            tech_key = f"tech_snapshot:{symbol}:{strategy_mode}"
            technical = await self._read_redis_json(tech_key)

            if technical is not None:
                logger.debug("Tech cache hit for %s/%s", symbol, strategy_mode)
            elif strategy_mode == "scalping":
                # 1m for entry timing, 5m for micro trend, 15m for context
                candles_1m = await self.client.get_historical_candles(symbol, "1m", 300)
                candles_5m = await self.client.get_historical_candles(symbol, "5m", 300)
                candles_15m = await self.client.get_historical_candles(symbol, "15m", 200)
                tech_1m = self.technical.analyze(candles_1m)
                tech_5m = self.technical.analyze(candles_5m)
                tech_15m = self.technical.analyze(candles_15m)
                technical = {
                    "timeframes": {"1m": tech_1m, "5m": tech_5m, "15m": tech_15m},
                    "overall_signal": self._weight_timeframes(tech_1m, tech_5m, tech_15m),
                }
                await self._write_redis_json(tech_key, technical, _TECH_SNAPSHOT_TTL)

            elif strategy_mode == "day_trading":
                # 5m for entries, 15m for trend, 1h for context
                candles_5m = await self.client.get_historical_candles(symbol, "5m", 300)
                candles_15m = await self.client.get_historical_candles(symbol, "15m", 200)
                candles_1h = await self.client.get_historical_candles(symbol, "1h", 150)
                tech_5m = self.technical.analyze(candles_5m)
                tech_15m = self.technical.analyze(candles_15m)
                tech_1h = self.technical.analyze(candles_1h)
                technical = {
                    "timeframes": {"5m": tech_5m, "15m": tech_15m, "1h": tech_1h},
                    "overall_signal": self._weight_timeframes(tech_5m, tech_15m, tech_1h),
                }
                await self._write_redis_json(tech_key, technical, _TECH_SNAPSHOT_TTL)

            else:  # swing (default)
                candles_1h = await self.client.get_historical_candles(symbol, "1h", 300)
                candles_4h = await self.client.get_historical_candles(symbol, "4h", 150)
                candles_d1 = await self.client.get_historical_candles(symbol, "1d", 100)
                tech_1h = self.technical.analyze(candles_1h)
                tech_4h = self.technical.analyze(candles_4h)
                tech_d1 = self.technical.analyze(candles_d1)
                technical = {
                    "timeframes": {"1h": tech_1h, "4h": tech_4h, "1d": tech_d1},
                    "overall_signal": self._weight_timeframes(tech_1h, tech_4h, tech_d1),
                }
                await self._write_redis_json(tech_key, technical, _TECH_SNAPSHOT_TTL)

        return {
            "symbol": symbol,
            "strategy_mode": strategy_mode,
            "technical": technical,
            "fundamental": await self.fundamental.analyze(symbol, db=db, as_of=as_of),
            "sentiment": sentiment,
            "macro": await self.macro.analyze(db=db, as_of=as_of),
        }

    async def analyze_multiple(self, symbols: list[str], strategy_mode: str = "scalping") -> list[dict]:
        """
        Analyze multiple symbols in parallel using asyncio.gather().
        This provides up to 10x speedup vs sequential analysis.
        """
        import asyncio
        coros = [self.gather_all(sym, strategy_mode) for sym in symbols]
        results = await asyncio.gather(*coros, return_exceptions=True)
        # Filter out exceptions and log them
        import logging
        logger = logging.getLogger("app.analysis.aggregator")
        clean_results = []
        for sym, res in zip(symbols, results):
            if isinstance(res, Exception):
                logger.warning("Analysis failed for %s: %s", sym, res, exc_info=True)
                continue
            clean_results.append(res)
        return clean_results

    def _weight_timeframes(self, tf1: dict, tf2: dict, tf3: dict) -> str:
        scores = {"bullish": 0, "bearish": 0, "neutral": 0}
        weights = {0: 0.3, 1: 0.35, 2: 0.35}
        for idx, tf in enumerate([tf1, tf2, tf3]):
            sig = tf.get("signal", "neutral")
            scores[sig] += weights[idx]
        return max(scores, key=scores.get)

    def _score_pair(self, analysis: dict) -> float:
        tech = analysis.get("technical", {})
        fund = analysis.get("fundamental", {})
        sent = analysis.get("sentiment", {})

        score = 0.0
        tech_signal = tech.get("overall_signal", "neutral")
        if tech_signal == "bullish":
            score += 0.4
        elif tech_signal == "bearish":
            score -= 0.4

        fund_bias = fund.get("direction_bias", "neutral")
        if fund_bias == "bullish":
            score += 0.35
        elif fund_bias == "bearish":
            score -= 0.35

        sent_signal = sent.get("overall_sentiment", "neutral")
        if sent_signal == "bullish":
            score += 0.25
        elif sent_signal == "bearish":
            score -= 0.25

        return score

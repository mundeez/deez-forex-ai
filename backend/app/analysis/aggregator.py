from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
from app.analysis.technical import TechnicalAnalyzer
from app.analysis.fundamental import FundamentalAnalyzer
from app.analysis.sentiment import SentimentAnalyzer
from app.config import get_settings
from app import schemas

settings = get_settings()


class AnalysisAggregator:
    def __init__(self, provider: schemas.DataProvider = None):
        self.provider = provider or settings.DATA_PROVIDER
        if self.provider == schemas.DataProvider.mt5_zmq:
            self.client = MT5ZMQClient()
        else:
            self.client = MetaApiClient()
        self.technical = TechnicalAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.sentiment = SentimentAnalyzer()

    async def gather_all(self, symbol: str = "EURUSD", strategy_mode: str = "scalping") -> dict:
        if strategy_mode == "scalping":
            # 1m for entry timing, 5m for micro trend, 15m for context
            candles_1m = await self.client.get_historical_candles(symbol, "1m", 300)
            candles_5m = await self.client.get_historical_candles(symbol, "5m", 300)
            candles_15m = await self.client.get_historical_candles(symbol, "15m", 200)

            tech_1m = self.technical.analyze(candles_1m)
            tech_5m = self.technical.analyze(candles_5m)
            tech_15m = self.technical.analyze(candles_15m)

            return {
                "symbol": symbol,
                "strategy_mode": strategy_mode,
                "technical": {
                    "timeframes": {
                        "1m": tech_1m,
                        "5m": tech_5m,
                        "15m": tech_15m,
                    },
                    "overall_signal": self._weight_timeframes(tech_1m, tech_5m, tech_15m),
                },
                "fundamental": await self.fundamental.analyze(symbol),
                "sentiment": await self.sentiment.analyze(symbol),
            }

        elif strategy_mode == "day_trading":
            # 5m for entries, 15m for trend, 1h for context
            candles_5m = await self.client.get_historical_candles(symbol, "5m", 300)
            candles_15m = await self.client.get_historical_candles(symbol, "15m", 200)
            candles_1h = await self.client.get_historical_candles(symbol, "1h", 150)

            tech_5m = self.technical.analyze(candles_5m)
            tech_15m = self.technical.analyze(candles_15m)
            tech_1h = self.technical.analyze(candles_1h)

            return {
                "symbol": symbol,
                "strategy_mode": strategy_mode,
                "technical": {
                    "timeframes": {
                        "5m": tech_5m,
                        "15m": tech_15m,
                        "1h": tech_1h,
                    },
                    "overall_signal": self._weight_timeframes(tech_5m, tech_15m, tech_1h),
                },
                "fundamental": await self.fundamental.analyze(symbol),
                "sentiment": await self.sentiment.analyze(symbol),
            }

        else:  # swing (default)
            candles_1h = await self.client.get_historical_candles(symbol, "1h", 300)
            candles_4h = await self.client.get_historical_candles(symbol, "4h", 150)
            candles_d1 = await self.client.get_historical_candles(symbol, "1d", 100)

            tech_1h = self.technical.analyze(candles_1h)
            tech_4h = self.technical.analyze(candles_4h)
            tech_d1 = self.technical.analyze(candles_d1)

            return {
                "symbol": symbol,
                "strategy_mode": strategy_mode,
                "technical": {
                    "timeframes": {
                        "1h": tech_1h,
                        "4h": tech_4h,
                        "1d": tech_d1,
                    },
                    "overall_signal": self._weight_timeframes(tech_1h, tech_4h, tech_d1),
                },
                "fundamental": await self.fundamental.analyze(symbol),
                "sentiment": await self.sentiment.analyze(symbol),
            }

    async def analyze_multiple(self, symbols: list[str], strategy_mode: str = "scalping") -> list[dict]:
        results = []
        for sym in symbols:
            analysis = await self.gather_all(sym, strategy_mode)
            results.append(analysis)
        return results

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

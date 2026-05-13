from app.services.data.metaapi_client import MetaApiClient
from app.analysis.technical import TechnicalAnalyzer
from app.analysis.fundamental import FundamentalAnalyzer
from app.analysis.sentiment import SentimentAnalyzer
from app.config import get_settings

settings = get_settings()


class AnalysisAggregator:
    def __init__(self):
        self.metaapi = MetaApiClient()
        self.technical = TechnicalAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.sentiment = SentimentAnalyzer()

    async def gather_all(self, symbol: str = "EURUSD") -> dict:
        candles_1h = await self.metaapi.get_historical_candles(symbol, "1h", 300)
        candles_4h = await self.metaapi.get_historical_candles(symbol, "4h", 150)
        candles_d1 = await self.metaapi.get_historical_candles(symbol, "1d", 100)

        tech_1h = self.technical.analyze(candles_1h)
        tech_4h = self.technical.analyze(candles_4h)
        tech_d1 = self.technical.analyze(candles_d1)

        fund = await self.fundamental.analyze(symbol)
        sent = await self.sentiment.analyze(symbol)

        return {
            "symbol": symbol,
            "technical": {
                "timeframes": {
                    "1h": tech_1h,
                    "4h": tech_4h,
                    "1d": tech_d1,
                },
                "overall_signal": self._weight_timeframes(tech_1h, tech_4h, tech_d1),
            },
            "fundamental": fund,
            "sentiment": sent,
        }

    async def analyze_multiple(self, symbols: list[str]) -> list[dict]:
        results = []
        for sym in symbols:
            analysis = await self.gather_all(sym)
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

import logging
import httpx
from typing import Dict, Any, List, Optional
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.analysis.sentiment")


class SentimentAnalyzer:
    def __init__(self):
        self.news_api_key = settings.NEWS_API_KEY

    async def analyze(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        retail = self._mock_retail_sentiment()
        news_sentiment = await self._analyze_news_sentiment(symbol)
        cot = self._mock_cot_data()

        overall = 0.0
        count = 0
        if retail.get("score") is not None:
            overall += retail["score"]
            count += 1
        if news_sentiment.get("score") is not None:
            overall += news_sentiment["score"]
            count += 1
        if cot.get("net_position") is not None:
            inst_score = 0.5 if cot["net_position"] > 0 else -0.5
            overall += inst_score
            count += 1

        avg_score = overall / count if count > 0 else 0.0
        bias = "neutral"
        if avg_score > 0.2:
            bias = "bullish"
        elif avg_score < -0.2:
            bias = "bearish"

        return {
            "overall_sentiment": bias,
            "sentiment_score": round(avg_score, 2),
            "retail": retail,
            "news": news_sentiment,
            "institutional": cot,
        }

    def _mock_retail_sentiment(self) -> Dict[str, Any]:
        return {
            "long_pct": 55.0,
            "short_pct": 45.0,
            "score": -0.1,
            "contrarian_signal": "bearish",
        }

    async def _analyze_news_sentiment(self, symbol: str) -> Dict[str, Any]:
        if not self.news_api_key:
            return {"score": 0.0, "headlines": ["Mock sentiment: slightly positive"]}

        headlines = await self._fetch_headlines(symbol)
        if not headlines:
            return {"score": 0.0, "headlines": []}

        pos_words = {"surge", "rally", "gain", "rise", "strong", "bullish", "growth", "up", "higher", "optimistic", "positive", "boost"}
        neg_words = {"drop", "fall", "crash", "decline", "weak", "bearish", "recession", "down", "lower", "pessimistic", "negative", "plunge"}

        score = 0.0
        for h in headlines:
            text = h.lower()
            pos = sum(1 for w in pos_words if w in text)
            neg = sum(1 for w in neg_words if w in text)
            if pos > neg:
                score += 0.2
            elif neg > pos:
                score -= 0.2

        score = max(-1.0, min(1.0, score))
        return {
            "score": round(score, 2),
            "headlines": headlines,
        }

    async def _fetch_headlines(self, symbol: str) -> List[str]:
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": f"{symbol[:3]} {symbol[3:]} forex OR EUR/USD",
                "apiKey": self.news_api_key,
                "sortBy": "publishedAt",
                "pageSize": 10,
                "language": "en",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            return [a["title"] for a in data.get("articles", [])]
        except Exception:
            logger.warning("Failed to fetch news headlines", exc_info=True)
            return []

    def _mock_cot_data(self) -> Dict[str, Any]:
        return {
            "report_date": "2024-05-07",
            "non_commercial_long": 85000,
            "non_commercial_short": 72000,
            "commercial_long": 110000,
            "commercial_short": 125000,
            "net_position": 13000,
            "institutional_bias": "bullish",
        }

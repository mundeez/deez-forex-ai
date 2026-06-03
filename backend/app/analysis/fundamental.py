import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from app.config import get_settings
from app.utils.time import utc_now

settings = get_settings()
logger = logging.getLogger("app.analysis.fundamental")


class FundamentalAnalyzer:
    def __init__(self):
        self.news_api_key = settings.NEWS_API_KEY
        self.fred_api_key = settings.FRED_API_KEY

    async def analyze(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        events = await self._fetch_economic_calendar()
        rate_diff = await self._fetch_interest_rate_spread()
        news = await self._fetch_news_headlines(symbol)

        high_impact_count = sum(1 for e in events if e.get("impact") == "high")
        event_risk = "low"
        if high_impact_count >= 2:
            event_risk = "high"
        elif high_impact_count == 1:
            event_risk = "medium"

        direction_bias = "neutral"
        if rate_diff is not None:
            direction_bias = "bearish" if rate_diff > 0 else "bullish"

        return {
            "event_risk": event_risk,
            "high_impact_events": high_impact_count,
            "events": events,
            "interest_rate_spread": rate_diff,
            "direction_bias": direction_bias,
            "news_headlines": news,
        }

    async def _fetch_economic_calendar(self) -> List[Dict[str, Any]]:
        if not self.news_api_key:
            return self._mock_events()
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                events = resp.json()
            now = utc_now()
            relevant = []
            for e in events:
                dt_str = e.get("date", "")
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
                except (ValueError, TypeError):
                    continue
                if dt >= now and dt <= now + timedelta(days=3):
                    country = e.get("country", "").upper()
                    if country in ("US", "EU", "DE", "FR", "IT"):
                        relevant.append({
                            "title": e.get("title"),
                            "country": country,
                            "date": dt.isoformat(),
                            "impact": e.get("impact", "low").lower(),
                            "forecast": e.get("forecast"),
                            "previous": e.get("previous"),
                        })
            return relevant[:10]
        except Exception:
            logger.warning("Failed to fetch economic calendar", exc_info=True)
            return self._mock_events()

    def _mock_events(self) -> List[Dict[str, Any]]:
        return [
            {
                "title": "US Non-Farm Payrolls",
                "country": "US",
                "date": (utc_now() + timedelta(days=1)).isoformat(),
                "impact": "high",
                "forecast": "185K",
                "previous": "175K",
            }
        ]

    async def _fetch_interest_rate_spread(self) -> Optional[float]:
        if not self.fred_api_key:
            return 1.25
        try:
            us_rate = await self._fred_series("DFEDTAR")
            eu_rate = await self._fred_series("ECBDFR")
            if us_rate and eu_rate:
                return round(us_rate - eu_rate, 2)
        except Exception:
            logger.warning("Failed to fetch interest rate spread from FRED", exc_info=True)
        return 1.25

    async def _fred_series(self, series_id: str) -> Optional[float]:
        url = f"https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": self.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            obs = data.get("observations", [])
            if obs:
                val = obs[0].get("value")
                return float(val) if val and val != "." else None
        return None

    async def _fetch_news_headlines(self, symbol: str) -> List[str]:
        if not self.news_api_key:
            return ["Mock headline: ECB signals potential rate cut"]
        try:
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": f"{symbol[:3]} {symbol[3:]} forex",
                "apiKey": self.news_api_key,
                "sortBy": "publishedAt",
                "pageSize": 5,
                "language": "en",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            return [a["title"] for a in data.get("articles", [])]
        except Exception:
            logger.warning("Failed to fetch news headlines", exc_info=True)
            return ["News unavailable"]

import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.utils.time import utc_now

settings = get_settings()
logger = logging.getLogger("app.analysis.fundamental")


class FundamentalAnalyzer:
    def __init__(self):
        self.news_api_key = settings.NEWS_API_KEY
        self.fred_api_key = settings.FRED_API_KEY

    async def analyze(
        self, symbol: str = "EURUSD", db: AsyncSession = None, as_of: datetime = None
    ) -> Dict[str, Any]:
        as_of = as_of or datetime.utcnow()
        if db is not None:
            events = await self._fetch_calendar_from_db(db, as_of)
        else:
            events = await self._fetch_economic_calendar()
        rate_diff = await self._fetch_interest_rate_spread(as_of=as_of, db=db)
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

        # Compute economic surprise index from events where actual > forecast
        surprise_score = self._compute_surprise_index(events)

        return {
            "event_risk": event_risk,
            "high_impact_events": high_impact_count,
            "events": events,
            "interest_rate_spread": rate_diff,
            "direction_bias": direction_bias,
            "news_headlines": news,
            "economic_surprise_index": surprise_score,
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

    async def _fetch_calendar_from_db(
        self, db: AsyncSession, as_of: datetime, window_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Return events within window_hours before/after as_of from economic_events table."""
        from app import models
        from sqlalchemy import select
        lo = as_of - timedelta(hours=window_hours)
        hi = as_of + timedelta(hours=window_hours)
        try:
            result = await db.execute(
                select(models.EconomicEvent)
                .where(models.EconomicEvent.timestamp >= lo)
                .where(models.EconomicEvent.timestamp <= hi)
                .order_by(models.EconomicEvent.timestamp)
            )
            rows = result.scalars().all()
            return [
                {
                    "title": row.event_name,
                    "country": row.currency,
                    "date": row.timestamp.isoformat() if row.timestamp else None,
                    "impact": row.impact,
                    "actual": row.actual,
                    "forecast": row.forecast,
                    "previous": row.previous,
                }
                for row in rows
            ]
        except Exception:
            logger.warning("Failed to fetch calendar from DB", exc_info=True)
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

    async def _fetch_interest_rate_spread(self, as_of: datetime = None, db: "AsyncSession" = None) -> Optional[float]:
        """Fetch interest rate spread from FRED API or fallback."""
        if not self.fred_api_key:
            return 1.25
        try:
            us_rate = await self._fred_series("DFEDTAR", as_of=as_of, db=db)
            eu_rate = await self._fred_series("ECBDFR", as_of=as_of, db=db)
            if us_rate and eu_rate:
                return round(us_rate - eu_rate, 2)
        except Exception:
            logger.warning("Failed to fetch interest rate spread from FRED", exc_info=True)
        return 1.25

    async def _fred_series(self, series_id: str, as_of: datetime = None,
                           db: "AsyncSession" = None) -> Optional[float]:
        """Fetch a FRED series value, optionally point-in-time from DB."""
        if as_of is not None and db is not None:
            from sqlalchemy import text as _text
            try:
                result = await db.execute(
                    _text("SELECT value FROM macro_series WHERE series_id = :sid "
                          "AND timestamp <= :as_of ORDER BY timestamp DESC LIMIT 1"),
                    {"sid": series_id, "as_of": as_of},
                )
                row = result.fetchone()
                if row:
                    return float(row[0])
            except Exception:
                pass  # fall through to API
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

    @staticmethod
    def _compute_surprise_index(events: List[Dict[str, Any]]) -> float:
        """Score how much actual results beat/miss forecasts.
        Returns a score between -1.0 and +1.0 where positive means
        actuals mostly beat forecasts (positive surprise).
        """
        surprises = []
        for e in events:
            actual = e.get("actual")
            forecast = e.get("forecast")
            if actual is not None and forecast is not None:
                try:
                    a_val = float(str(actual).replace("K", "").replace("M", "").replace("%", "").replace(",", "").strip())
                    f_val = float(str(forecast).replace("K", "").replace("M", "").replace("%", "").replace(",", "").strip())
                    if f_val != 0:
                        surprises.append((a_val - f_val) / abs(f_val))
                except (ValueError, TypeError):
                    continue
        if not surprises:
            return 0.0
        avg_surprise = sum(surprises) / len(surprises)
        return round(max(-1.0, min(1.0, avg_surprise)), 2)

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

"""News and economic calendar service for trading halt decisions."""
import json
import logging
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.news")

# Free ForexFactory calendar endpoint (JSON)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Default high-impact events that always trigger a halt
HIGH_IMPACT_KEYWORDS = [
    "non-farm", "nfp", "fomc", "fed", "interest rate", "cpi", "gdp",
    "ecb", "boe", "boj", " unemployment", "retail sales", "pmi",
    "inflation", "monetary policy", "press conference",
]

CURRENCY_PAIR_IMPACT = {
    "EURUSD": ["EUR", "USD", "EU", "US", "FOMC", "Fed", "ECB"],
    "GBPUSD": ["GBP", "USD", "UK", "US", "BOE", "FOMC", "Fed"],
    "USDJPY": ["USD", "JPY", "US", "JP", "BOJ", "FOMC", "Fed"],
    "AUDUSD": ["AUD", "USD", "AU", "US", "RBA", "FOMC", "Fed"],
    "USDCAD": ["USD", "CAD", "US", "CA", "BOC", "FOMC", "Fed"],
    "USDCHF": ["USD", "CHF", "US", "CH", "SNB", "FOMC", "Fed"],
    "NZDUSD": ["NZD", "USD", "NZ", "US", "RBNZ", "FOMC", "Fed"],
    "EURGBP": ["EUR", "GBP", "EU", "UK", "ECB", "BOE"],
    "GBPJPY": ["GBP", "JPY", "UK", "JP", "BOE", "BOJ"],
    "XAUUSD": ["USD", "US", "FOMC", "Fed", "CPI", "inflation", "NFP"],
}


class NewsService:
    def __init__(self):
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._cache_time: Optional[datetime] = None
        self.cache_ttl_minutes = 15

    async def _fetch_calendar(self) -> List[Dict[str, Any]]:
        """Fetch this week's economic calendar from free source."""
        if self._cache and self._cache_time:
            if datetime.utcnow() - self._cache_time < timedelta(minutes=self.cache_ttl_minutes):
                return self._cache

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(FF_CALENDAR_URL)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    self._cache = data
                    self._cache_time = datetime.utcnow()
                    return data
        except Exception:
            logger.warning("Failed to fetch economic calendar", exc_info=True)

        # Fallback: empty list
        return []

    def _parse_event_time(self, event: Dict[str, Any]) -> Optional[datetime]:
        """Parse event datetime from ForexFactory JSON format."""
        import pytz
        date_str = event.get("date")
        time_str = event.get("time")
        if not date_str:
            return None
        try:
            # ForexFactory format: "2024-01-15" and "08:30"
            # They use US Eastern Time (EST/EDT) - must use pytz for correct DST handling
            dt_str = f"{date_str} {time_str or '00:00'}"
            eastern = pytz.timezone("US/Eastern")
            naive_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            localized_dt = eastern.localize(naive_dt)
            return localized_dt.astimezone(pytz.utc).replace(tzinfo=None)
        except Exception:
            logger.warning("Failed to parse event time", exc_info=True)
            return None

    def _is_high_impact(self, event: Dict[str, Any]) -> bool:
        """Check if event is high impact."""
        impact = str(event.get("impact", "")).lower()
        if impact in ("high", "3"):
            return True
        title = str(event.get("title", "")).lower()
        for kw in HIGH_IMPACT_KEYWORDS:
            if kw.lower() in title:
                return True
        return False

    def _event_affects_symbol(self, event: Dict[str, Any], symbol: str) -> bool:
        """Check if event affects the given currency pair."""
        title = str(event.get("title", "")).upper()
        country = str(event.get("country", "")).upper()
        impact_keywords = CURRENCY_PAIR_IMPACT.get(symbol, [])
        for kw in impact_keywords:
            if kw.upper() in title or kw.upper() in country:
                return True
        # Also check based on symbol currencies directly
        base = symbol[:3]
        quote = symbol[3:] if len(symbol) == 6 else "USD"
        if base.upper() in country or quote.upper() in country:
            return True
        return False

    async def is_trading_halted(
        self,
        symbol: str,
        buffer_minutes_before: int = 15,
        buffer_minutes_after: int = 30,
    ) -> Tuple[bool, str]:
        """Check if trading should be halted due to upcoming high-impact news."""
        events = await self._fetch_calendar()
        now = datetime.utcnow()

        for event in events:
            if not self._is_high_impact(event):
                continue
            if not self._event_affects_symbol(event, symbol):
                continue

            event_time = self._parse_event_time(event)
            if not event_time:
                continue

            window_start = event_time - timedelta(minutes=buffer_minutes_before)
            window_end = event_time + timedelta(minutes=buffer_minutes_after)

            if window_start <= now <= window_end:
                title = event.get("title", "Unknown event")
                return True, f"Trading halted: {title} at {event_time.strftime('%H:%M UTC')} ({buffer_minutes_before}min before — {buffer_minutes_after}min after)"

        return False, ""

    async def get_upcoming_events(self, symbol: str, hours_ahead: int = 24) -> List[Dict[str, Any]]:
        """Get upcoming high-impact events for a symbol."""
        events = await self._fetch_calendar()
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours_ahead)
        results = []
        for event in events:
            if not self._is_high_impact(event):
                continue
            if not self._event_affects_symbol(event, symbol):
                continue
            event_time = self._parse_event_time(event)
            if event_time and now <= event_time <= cutoff:
                results.append({
                    "title": event.get("title"),
                    "time": event_time.isoformat(),
                    "impact": event.get("impact"),
                    "country": event.get("country"),
                })
        return results

"""ForexFactory economic calendar ingestion.

Scrapes the ForexFactory calendar website for historical economic events.
The FF calendar is available at https://www.forexfactory.com/calendar?day=YYYYMMDD
and returns events for each day.

For the backtest period (Oct 2025 – Jun 2026), we scrape week by week.
The live JSON endpoint (nfs.faireconomy.media) is used for the current week.

Usage:
    docker compose exec backend python3 -c "
    import asyncio
    from datetime import date
    from app.services.data.ff_client import ingest_calendar
    from app.database import get_celery_session

    async def run():
        async with get_celery_session()() as db:
            n = await ingest_calendar(db, date(2025, 10, 1), date(2026, 6, 19))
            print(f'Inserted {n} economic events')

    asyncio.run(run())
    """
import logging
import re
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("app.services.data.ff")

CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"}

# ForexFactory calendar URL — can filter by day
FF_CALENDAR_URL = "https://www.forexfactory.com/calendar?day={date}"

# ForexFactory JSON endpoint (this week only)
FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Headers to avoid being blocked
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


async def ingest_calendar(db: AsyncSession, start: date, end: date) -> int:
    """Scrape ForexFactory calendar events and insert into economic_events table.

    Returns the number of rows inserted.
    """
    total = 0

    # --- Try live JSON endpoint first (covers current week) ---
    total += await _ingest_from_live_json(db, start, end)
    logger.info("ForexFactory live JSON: %d events so far", total)

    # --- Scrape historical weeks ---
    # FF calendar pages are per-day. We iterate day by day.
    current = start
    while current <= end:
        if current.weekday() >= 5:  # Skip weekends
            current += timedelta(days=1)
            continue
        try:
            count = await _scrape_day(db, current)
            total += count
            if count > 0:
                logger.debug("FF scrape %s: %d events", current, count)
        except Exception as e:
            logger.debug("FF scrape failed for %s: %s", current, e)

        current += timedelta(days=1)

    logger.info("ForexFactory ingestion complete: %d total events", total)
    return total


async def _ingest_from_live_json(db: AsyncSession, start: date, end: date) -> int:
    """Fetch this week's events from the live ForexFactory JSON endpoint."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(FF_JSON_URL)
            resp.raise_for_status()
            events = resp.json()
    except Exception:
        logger.warning("Failed to fetch ForexFactory live JSON", exc_info=True)
        return 0

    stmt = text("""
        INSERT INTO economic_events
            (timestamp, currency, event_name, impact, actual, forecast, previous, source)
        VALUES
            (:timestamp, :currency, :event_name, :impact, :actual, :forecast, :previous, :source)
        ON CONFLICT DO NOTHING
    """)

    count = 0
    for e in events:
        try:
            dt_str = e.get("date", "")
            dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
            d = dt.date()
            if d < start or d > end:
                continue
            currency = e.get("country", "").upper()
            if currency not in CURRENCIES:
                continue
            await db.execute(stmt, {
                "timestamp": dt,
                "currency": currency,
                "event_name": e.get("title", ""),
                "impact": e.get("impact", "low").lower(),
                "actual": _safe_str(e.get("actual")),
                "forecast": _safe_str(e.get("forecast")),
                "previous": _safe_str(e.get("previous")),
                "source": "forexfactory_live",
            })
            count += 1
        except (ValueError, TypeError):
            continue
        except Exception:
            pass

    await db.commit()
    return count


async def _scrape_day(db: AsyncSession, target_date: date) -> int:
    """Scrape a single day's calendar from ForexFactory."""
    date_str = target_date.strftime("%b%d.%Y").lower()
    # FF URL format: jan01.2026
    url = FF_CALENDAR_URL.format(date=date_str)

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception:
        return 0

    events = _parse_ff_html(html, target_date)
    if not events:
        return 0

    stmt = text("""
        INSERT INTO economic_events
            (timestamp, currency, event_name, impact, actual, forecast, previous, source)
        VALUES
            (:timestamp, :currency, :event_name, :impact, :actual, :forecast, :previous, :source)
        ON CONFLICT DO NOTHING
    """)

    count = 0
    for e in events:
        try:
            await db.execute(stmt, {
                "timestamp": e["timestamp"],
                "currency": e["currency"],
                "event_name": e["event_name"],
                "impact": e["impact"],
                "actual": e.get("actual"),
                "forecast": e.get("forecast"),
                "previous": e.get("previous"),
                "source": "forexfactory_scrape",
            })
            count += 1
        except Exception:
            pass

    await db.commit()
    return count


def _parse_ff_html(html: str, target_date: date) -> List[Dict[str, Any]]:
    """Parse ForexFactory calendar HTML to extract events.

    FF calendar rows use <tr> elements with class "calendar__row" and data
    attributes. We use a lightweight regex-based parser since the HTML structure
    can vary.
    """
    events = []

    # Find all calendar row blocks
    # FF uses <tr class="calendar__row ..."> with <td> cells for:
    # time, currency, impact, event, actual, forecast, previous
    row_pattern = re.compile(
        r'<tr[^>]*class="[^"]*calendar__row[^"]*"[^>]*>(.*?)</tr>',
        re.DOTALL
    )

    for row_match in row_pattern.finditer(html):
        row_html = row_match.group(1)

        # Extract currency (3-letter code in a span)
        currency = _extract_text(row_html, r'class="[^"]*calendar__cell[^"]*currency[^"]*"[^>]*>(.*?)</td>')
        if not currency:
            continue
        currency = currency.strip().upper()
        if currency not in CURRENCIES:
            continue

        # Extract event title
        event_name = _extract_text(row_html, r'class="[^"]*calendar__cell[^"]*event[^"]*"[^>]*>(.*?)</td>')
        if not event_name:
            continue
        # Clean HTML tags from event name
        event_name = re.sub(r'<[^>]+>', '', event_name).strip()
        if not event_name:
            continue

        # Extract impact
        impact_class = re.search(r'class="[^"]*calendar__impact[^"]*(high|medium|low|holiday)[^"]*"', row_html)
        impact = "low"
        if impact_class:
            impact = impact_class.group(1)
            if impact == "holiday":
                impact = "low"

        # Extract time
        time_str = _extract_text(row_html, r'class="[^"]*calendar__cell[^"]*time[^"]*"[^>]*>(.*?)</td>')
        time_str = re.sub(r'<[^>]+>', '', time_str).strip() if time_str else ""

        # Build timestamp
        ts = _build_timestamp(time_str, target_date)

        # Extract actual, forecast, previous
        actual = _extract_text(row_html, r'class="[^"]*calendar__cell[^"]*actual[^"]*"[^>]*>(.*?)</td>')
        forecast = _extract_text(row_html, r'class="[^"]*calendar__cell[^"]*forecast[^"]*"[^>]*>(.*?)</td>')
        previous = _extract_text(row_html, r'class="[^"]*calendar__cell[^"]*previous[^"]*"[^>]*>(.*?)</td>')

        events.append({
            "timestamp": ts,
            "currency": currency,
            "event_name": event_name[:300],
            "impact": impact,
            "actual": _safe_str(_clean_text(actual)),
            "forecast": _safe_str(_clean_text(forecast)),
            "previous": _safe_str(_clean_text(previous)),
        })

    return events


def _extract_text(html: str, pattern: str) -> Optional[str]:
    """Extract text content from an HTML cell using a regex pattern."""
    match = re.search(pattern, html, re.DOTALL)
    if match:
        return match.group(1)
    return None


def _clean_text(text: Optional[str]) -> str:
    """Remove HTML tags and clean whitespace."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


def _build_timestamp(time_str: str, target_date: date) -> datetime:
    """Build a datetime from a time string and date.

    FF times can be "8:30am", "All Day", "Tentative", or empty.
    """
    time_str = time_str.strip()
    if not time_str or time_str.lower() in ("all day", "tentative", ""):
        return datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)

    # Try parsing "H:MMam" or "H:MMpm"
    for fmt in ("%I:%M%p", "%I:%M:%S%p", "%H:%M"):
        try:
            # Normalize: "8:30am" -> "8:30AM"
            normalized = time_str.lower().replace(" ", "").upper()
            t = datetime.strptime(normalized, fmt).time()
            return datetime.combine(target_date, t)
        except ValueError:
            continue

    return datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)


def _safe_str(val) -> Optional[str]:
    """Convert a value to string or None, treating empty/dot as None."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s == ".":
        return None
    return s

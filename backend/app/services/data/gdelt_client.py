"""GDELT news headline ingestion for historical backtest simulation.

GDELT Project (gdeltproject.org) provides global news event data at 15-minute
resolution. This client downloads GDELT 2.0 GKG (Global Knowledge Graph) files
for a date range, extracts forex-relevant headlines, runs a lightweight keyword-
based sentiment scoring, and stores them in the news_headlines table.

Coverage note: GDELT coverage is spotty for Oct 2025–Feb 2026 but strong from
Mar 2026 onward. For dates with no GDELT data, the news_headlines table will
simply have no rows, and the sentiment analyzer will return neutral — which is
the correct behaviour (no look-ahead bias).

Usage:
    docker compose exec backend python3 -c "
    import asyncio
    from datetime import date
    from app.services.data.gdelt_client import ingest_gdelt_news
    from app.database import get_celery_session

    async def run():
        async with get_celery_session()() as db:
            n = await ingest_gdelt_news(db, date(2025, 10, 15), date(2026, 6, 19))
            print(f'Inserted {n} news headlines')

    asyncio.run(run())
    "
"""
import logging
import gzip
import io
import csv
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# GDELT GKG fields can be very large (themes, locations, etc.)
csv.field_size_limit(256 * 1024 * 1024)  # 256MB

logger = logging.getLogger("app.services.data.gdelt")

# GDELT 2.0 GKG URL pattern — 15-minute resolution
# Format: YYYYMMDDHHMMSS
GDELT_GKG_URL = "http://data.gdeltproject.org/gdeltv2/{ts}.gkg.csv.zip"
GDELT_GKG_BASE = "http://data.gdeltproject.org/gdeltv2/masterfilelist-translation.txt"

# Forex-relevant keywords for filtering GDELT themes
FOREX_KEYWORDS = [
    "forex", "currency", "dollar", "euro", "pound", "yen", "fed", "ecb",
    "boe", "boj", "interest rate", "inflation", "cpi", "nonfarm", "nfp",
    "trade war", "tariff", "recession", "central bank", "monetary policy",
    "usd", "eur", "gbp", "jpy", "aud", "cad", "chf", "nzd",
]

# Keyword-based sentiment scoring
POSITIVE_WORDS = {"surge", "rally", "gain", "rise", "strong", "bullish", "growth",
                  "up", "higher", "optimistic", "positive", "boost", "soar", "breakout"}
NEGATIVE_WORDS = {"drop", "fall", "crash", "decline", "weak", "bearish", "recession",
                  "down", "lower", "pessimistic", "negative", "plunge", "collapse",
                  "slump", "downturn", "panic"}

# GDELT GKG CSV column layout (v2.0)
# Column 23 = V2Themes, Column 4 = V2Locations, Column 9 = V2Persons,
# Column 27 = V2EnhancedDates, Column 23+25 = V2Tone
# We use a simplified approach: column 0 = date, column 5 = Source URL,
# and we extract the title from the URL/title field.
# The GKG CSV has no header row. Key columns:
#   0: DATE (YYYYMMDDHHMMSS)
#   1: NUMARTS
#   4: SOURCEURLS
#   34: V2Tone (comma-separated tone scores)
# We'll use a lightweight parse focusing on these.


async def ingest_gdelt_news(
    db: AsyncSession, start: date, end: date, sample_interval_minutes: int = 60
) -> int:
    """Download GDELT GKG files for the date range and insert forex-relevant headlines.

    Args:
        db: Database session
        start: Start date (inclusive)
        end: End date (inclusive)
        sample_interval_minutes: Download one GKG file every N minutes (15 = all,
                                 60 = hourly, 360 = every 6 hours). Higher = faster but
                                 fewer headlines.

    Returns: Number of rows inserted.
    """
    total = 0
    current = datetime(start.year, start.month, start.day, 0, 0, 0)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59)

    # Round current to the nearest 15-minute interval
    current = current.replace(minute=(current.minute // 15) * 15, second=0, microsecond=0)

    logger.info("GDELT ingestion: %s to %s (every %d min)", current, end_dt, sample_interval_minutes)

    stmt = text("""
        INSERT INTO news_headlines
            (published_at, symbol, headline, source, finbert_positive,
             finbert_negative, finbert_neutral, composite_score, processed)
        VALUES
            (:published_at, :symbol, :headline, :source, 0.0, 0.0, 1.0, :score, true)
        ON CONFLICT DO NOTHING
    """)

    batch = []
    while current <= end_dt:
        ts = current.strftime("%Y%m%d%H%M%S")
        url = GDELT_GKG_URL.format(ts=ts)

        try:
            rows = await _download_and_parse_gkg(url)
            for row in rows:
                if not _is_forex_relevant(row.get("headline", "")):
                    continue
                score = _score_headline(row.get("headline", ""))
                batch.append({
                    "published_at": row["date"],
                    "symbol": None,  # GDELT headlines are global, not pair-specific
                    "headline": row["headline"][:500],
                    "source": "gdelt",
                    "score": score,
                })

            # Flush batch every 500 rows
            if len(batch) >= 500:
                total += await _flush_batch(db, stmt, batch)
                batch = []

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                pass  # Normal — not all 15-min slots have a GKG file
            else:
                logger.debug("GDELT HTTP %s for %s", e.response.status_code, ts)
        except Exception as e:
            logger.debug("GDELT parse failed for %s: %s", ts, e)

        current += timedelta(minutes=sample_interval_minutes)

    # Flush remaining
    if batch:
        total += await _flush_batch(db, stmt, batch)

    logger.info("GDELT ingestion complete: %d headlines inserted", total)
    return total


async def _download_and_parse_gkg(url: str) -> List[Dict[str, Any]]:
    """Download and parse a single GDELT GKG CSV file."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    # GDELT GKG files are ZIP-compressed CSVs with no header
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(resp.content))
    csv_filename = z.namelist()[0]
    csv_content = z.read(csv_filename).decode("utf-8", errors="replace")

    rows = []
    reader = csv.reader(io.StringIO(csv_content), delimiter='\t')
    for fields in reader:
        if len(fields) < 5:
            continue
        try:
            date_str = fields[0]
            # GDELT date field may have a "-N" suffix (e.g. "20260301060000-0")
            date_str = date_str.split("-")[0]
            dt = datetime.strptime(date_str, "%Y%m%d%H%M%S")
            url_field = fields[4] if len(fields) > 4 else ""
            # Extract headline from URL (best-effort — GDELT doesn't store titles directly)
            headline = _extract_headline_from_url(url_field)
            if headline:
                rows.append({"date": dt, "headline": headline, "url": url_field})
        except (ValueError, IndexError):
            continue

    return rows


def _extract_headline_from_url(url: str) -> str:
    """Best-effort extraction of a headline-like string from a URL."""
    if not url:
        return ""
    # Remove protocol and domain, take the path as a proxy for headline
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        # Replace separators with spaces
        headline = path.replace("-", " ").replace("_", " ").replace("/", " ")
        # Remove file extensions
        for ext in [".html", ".htm", ".php", ".asp"]:
            headline = headline.replace(ext, "")
        return headline.strip()[:300]
    except Exception:
        return ""


def _is_forex_relevant(text: str) -> bool:
    """Check if a headline contains forex-relevant keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in FOREX_KEYWORDS)


def _score_headline(headline: str) -> float:
    """Simple keyword-based sentiment score (-1.0 to +1.0)."""
    text = headline.lower()
    words = set(text.split())
    pos = sum(1 for w in POSITIVE_WORDS if w in words)
    neg = sum(1 for w in NEGATIVE_WORDS if w in words)
    if pos > neg:
        return min(0.5 * pos, 1.0)
    elif neg > pos:
        return max(-0.5 * neg, -1.0)
    return 0.0


async def _flush_batch(db: AsyncSession, stmt, batch: List[Dict]) -> int:
    """Execute a batch of inserts and commit."""
    count = 0
    for item in batch:
        try:
            await db.execute(stmt, item)
            count += 1
        except Exception:
            pass
    await db.commit()
    return count

"""Retail sentiment ingestion client.

Two modes:
  1. backfill_from_cot() — derive historical retail sentiment from CFTC COT
     non-commercial (speculator) positions as a proxy.  Non-commercial traders
     (hedge funds, CTAs, large retail) tend to be on the same side as the
     retail crowd at extremes, making this a reasonable proxy for historical
     backtesting when no direct retail sentiment history exists.

  2. scrape_myfxbook() — scrape the current Myfxbook community outlook
     snapshot for live forward trading.  NOTE: Myfxbook is behind Cloudflare
     which blocks simple HTTP requests (403 challenge).  This requires a
     headless browser (Playwright/Selenium) or an authenticated API session
     to work.  Left as a stub for future implementation.

Usage (backfill):
    docker compose exec backend python3 -c "
    import asyncio
    from app.services.data.retail_client import backfill_from_cot
    from app.database import get_celery_session

    async def run():
        async with get_celery_session()() as db:
            n = await backfill_from_cot(db)
            print(f'Inserted {n} retail sentiment rows')

    asyncio.run(run())
    "

Usage (live scrape):
    docker compose exec backend python3 -c "
    import asyncio
    from app.services.data.retail_client import scrape_myfxbook
    from app.database import get_celery_session

    async def run():
        async with get_celery_session()() as db:
            n = await scrape_myfxbook(db)
            print(f'Inserted {n} live retail sentiment rows')

    asyncio.run(run())
    """
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

from app import models

logger = logging.getLogger("app.services.data.retail")

# Symbols we track (must match COT symbol names)
SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD",
]


async def backfill_from_cot(db: AsyncSession) -> int:
    """Derive historical retail sentiment from COT non-commercial positions.

    For each COT report row, convert nc_long / nc_short into percentages:
        long_pct  = nc_long  / (nc_long + nc_short) * 100
        short_pct = nc_short / (nc_long + nc_short) * 100
        net_score = (long_pct - short_pct) / 100

    Only inserts rows that don't already exist (avoids duplicates on re-run).
    """
    # Fetch all COT rows, ordered by date
    result = await db.execute(
        text("""
            SELECT report_date, symbol, nc_long, nc_short, nc_net, open_interest
            FROM cot_reports
            WHERE nc_long IS NOT NULL AND nc_short IS NOT NULL
              AND (nc_long + nc_short) > 0
            ORDER BY report_date, symbol
        """)
    )
    cot_rows = result.fetchall()

    if not cot_rows:
        logger.warning("[retail] No COT data found to backfill from")
        return 0

    # Check which (timestamp, symbol) pairs already exist in retail_sentiment
    existing_result = await db.execute(
        text("SELECT timestamp, symbol FROM retail_sentiment WHERE source = 'cot_proxy'")
    )
    existing = {(row[0], row[1]) for row in existing_result.fetchall()}

    inserted = 0
    batch = []
    for row in cot_rows:
        report_date, symbol, nc_long, nc_short, nc_net, oi = row
        # Skip if already exists
        if (report_date, symbol) in existing:
            continue

        total = nc_long + nc_short
        long_pct = round((nc_long / total) * 100, 1)
        short_pct = round((nc_short / total) * 100, 1)
        net_score = round((long_pct - short_pct) / 100.0, 4)

        batch.append({
            "timestamp": report_date,
            "symbol": symbol,
            "long_pct": long_pct,
            "short_pct": short_pct,
            "net_score": net_score,
            "source": "cot_proxy",
        })
        inserted += 1

        # Flush in batches of 500
        if len(batch) >= 500:
            await _bulk_insert(db, batch)
            batch = []

    if batch:
        await _bulk_insert(db, batch)

    await db.commit()
    logger.info("[retail] Backfilled %d retail sentiment rows from COT proxy", inserted)
    return inserted


async def scrape_myfxbook(db: AsyncSession) -> int:
    """Scrape current Myfxbook community outlook for all symbols.

    Returns the number of rows inserted.  Intended to be called periodically
    (e.g. every hour) to build a live retail sentiment history.
    """
    now = datetime.now(timezone.utc)
    inserted = 0

    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ForexAI/1.0)"}
    ) as client:
        for symbol in SYMBOLS:
            try:
                data = await _scrape_symbol(client, symbol)
                if data is None:
                    continue

                row = models.RetailSentiment(
                    timestamp=now,
                    symbol=symbol,
                    long_pct=data["long_pct"],
                    short_pct=data["short_pct"],
                    net_score=data["net_score"],
                    source="myfxbook",
                )
                db.add(row)
                inserted += 1
            except Exception:
                logger.warning("[retail] Myfxbook scrape failed for %s", symbol, exc_info=True)

    if inserted > 0:
        await db.commit()
    logger.info("[retail] Scraped %d live retail sentiment rows from Myfxbook", inserted)
    return inserted


async def _scrape_symbol(client: httpx.AsyncClient, symbol: str) -> Dict[str, Any] | None:
    """Scrape a single symbol's community outlook from Myfxbook."""
    url = f"https://www.myfxbook.com/community/outlook/{symbol}"
    resp = await client.get(url)
    if resp.status_code != 200:
        return None

    text = resp.text
    # Look for patterns like "55% Long" / "45% Short" or JSON data blocks
    long_match = re.search(r'(\d+(?:\.\d+)?)\s*%?\s*[Ll]ong', text)
    short_match = re.search(r'(\d+(?:\.\d+)?)\s*%?\s*[Ss]hort', text)

    if not long_match or not short_match:
        return None

    long_pct = float(long_match.group(1))
    short_pct = float(short_match.group(1))

    # Sanity check: percentages should sum to ~100
    if abs(long_pct + short_pct - 100.0) > 5.0:
        logger.warning("[retail] Myfxbook %s: long+short=%.1f (expected ~100), skipping",
                       symbol, long_pct + short_pct)
        return None

    net_score = round((long_pct - short_pct) / 100.0, 4)
    return {
        "long_pct": round(long_pct, 1),
        "short_pct": round(short_pct, 1),
        "net_score": net_score,
    }


async def _bulk_insert(db: AsyncSession, rows: List[Dict[str, Any]]):
    """Bulk insert retail sentiment rows."""
    if not rows:
        return
    await db.execute(
        text("""
            INSERT INTO retail_sentiment (timestamp, symbol, long_pct, short_pct, net_score, source)
            VALUES (:timestamp, :symbol, :long_pct, :short_pct, :net_score, :source)
            ON CONFLICT DO NOTHING
        """),
        rows,
    )

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
from datetime import datetime, timezone
from typing import List, Dict, Any
import os

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


MYFXBOOK_API = "https://www.myfxbook.com/api"


async def scrape_myfxbook(db: AsyncSession) -> int:
    """Fetch live community outlook via the official Myfxbook JSON API.

    Requires MYFXBOOK_EMAIL + MYFXBOOK_PASSWORD env vars — the API uses
    account credentials (login.json returns a session token), not an API
    key.  The /api/* endpoints serve JSON directly and are not behind the
    Cloudflare browser challenge that made HTML scraping impossible.

    Inserts one snapshot row per tracked symbol.  Returns rows inserted;
    0 means no credentials configured or the call failed (caller falls
    back to the COT proxy).
    """
    email = os.environ.get("MYFXBOOK_EMAIL", "")
    password = os.environ.get("MYFXBOOK_PASSWORD", "")
    if not email or not password:
        return 0

    now = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ForexAI/1.0)"}
    ) as client:
        try:
            resp = await client.get(
                f"{MYFXBOOK_API}/login.json",
                params={"email": email, "password": password},
            )
            payload = resp.json()
            if payload.get("error") or not payload.get("session"):
                logger.warning("[retail] Myfxbook login failed: %s", payload.get("message", ""))
                return 0
            session = payload["session"]
        except Exception as exc:
            logger.warning("[retail] Myfxbook login request failed: %s", exc)
            return 0

        try:
            resp = await client.get(
                f"{MYFXBOOK_API}/get-community-outlook.json",
                params={"session": session},
            )
            data = resp.json()
            if data.get("error"):
                logger.warning("[retail] Myfxbook outlook error: %s", data.get("message", ""))
                return 0

            for sym in data.get("symbols", []):
                name = (sym.get("name") or "").upper()
                if name not in SYMBOLS:
                    continue
                try:
                    long_pct = float(sym.get("longPercentage") or 0)
                    short_pct = float(sym.get("shortPercentage") or 0)
                except (TypeError, ValueError):
                    continue
                # API returns fractions (0–1); normalize to 0–100
                if 0 < long_pct <= 1.0 and 0 < short_pct <= 1.0:
                    long_pct, short_pct = long_pct * 100, short_pct * 100
                if long_pct + short_pct <= 0:
                    continue
                rows.append({
                    "timestamp": now,
                    "symbol": name,
                    "long_pct": round(long_pct, 1),
                    "short_pct": round(short_pct, 1),
                    "net_score": round((long_pct - short_pct) / 100.0, 4),
                    "source": "myfxbook",
                })
        except Exception as exc:
            logger.warning("[retail] Myfxbook outlook request failed: %s", exc)
            return 0
        finally:
            try:
                await client.get(f"{MYFXBOOK_API}/logout.json", params={"session": session})
            except Exception:
                pass

    if rows:
        await _bulk_insert(db, rows)
        await db.commit()
    logger.info("[retail] Fetched %d live retail sentiment rows from Myfxbook API", len(rows))
    return len(rows)


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

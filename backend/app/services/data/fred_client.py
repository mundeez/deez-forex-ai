"""FRED API client for macroeconomic data ingestion.

Fetches 11 key US / global macro series and stores them in the macro_series table.
Free API key required from https://fred.stlouisfed.org/docs/api/api_key.html
"""
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_celery_session
from app import models

logger = logging.getLogger("app.services.data.fred")

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Key series for forex macro context
FRED_SERIES = {
    "DFEDTAR": "US Federal Funds Target Rate",
    "FEDFUNDS": "US Federal Funds Effective Rate",
    "CPIAUCSL": "US CPI All Urban Consumers",
    "UNRATE": "US Unemployment Rate",
    "DGS10": "US 10-Year Treasury Yield",
    "DGS2": "US 2-Year Treasury Yield",
    "DGS30": "US 30-Year Treasury Yield",
    "T10Y2Y": "US 10Y-2Y Yield Spread",
    "ECBDFR": "ECB Deposit Facility Rate",
    "VIXCLS": "VIX Close",
    "T10YIE": "US 10Y Breakeven Inflation",
    "BAMLH0A0HYM2": "US High Yield Spread",
    "DTWEXBGS": "US Dollar Broad Index (DXY proxy)",
    "DCOILWTICO": "WTI Crude Oil Price",
    "GOLDPMGBD228NLBM": "Gold Price PM Fix",
    "SP500": "S&P 500 Index",
}


class FREDClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or FRED_API_KEY
        if not self.api_key:
            logger.warning("FRED_API_KEY not set — FRED ingestion will be no-op")

    async def fetch_series(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch observations for a single FRED series."""
        if not self.api_key:
            return []

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1000,
        }
        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(FRED_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

        observations = data.get("observations", [])
        out = []
        for obs in observations:
            val = obs.get("value")
            if val is None or val == ".":
                continue
            try:
                out.append({
                    "timestamp": datetime.strptime(obs["date"], "%Y-%m-%d"),
                    "series_id": series_id,
                    "value": float(val),
                    "source": "fred",
                })
            except (ValueError, TypeError):
                continue
        return out

    async def ingest_all(
        self,
        db: AsyncSession,
        lookback_days: int = 365,
    ) -> Dict[str, int]:
        """Ingest all configured FRED series into macro_series."""
        if not self.api_key:
            logger.warning("Skipping FRED ingestion — no API key")
            return {}

        end = datetime.utcnow().date()
        start = (end - timedelta(days=lookback_days)).isoformat()
        end_str = end.isoformat()

        totals = {}
        for series_id in FRED_SERIES:
            try:
                rows = await self.fetch_series(series_id, start, end_str)
                if not rows:
                    totals[series_id] = 0
                    continue

                # Bulk insert via raw SQL for speed (upsert on conflict)
                from sqlalchemy import text
                stmt = text("""
                    INSERT INTO macro_series (timestamp, series_id, value, source)
                    VALUES (:timestamp, :series_id, :value, :source)
                    ON CONFLICT (series_id, timestamp) DO NOTHING
                """)
                count = 0
                for row in rows:
                    try:
                        await db.execute(stmt, row)
                        count += 1
                    except Exception:
                        pass
                await db.commit()
                totals[series_id] = count
                logger.info("FRED %s: inserted %d rows", series_id, count)
            except Exception as exc:
                logger.error("FRED %s ingestion failed: %s", series_id, exc)
                totals[series_id] = 0
        return totals

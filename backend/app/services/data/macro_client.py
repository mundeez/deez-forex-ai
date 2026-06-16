"""yfinance macro data ingestion client.

Fetches DXY, VIX, indices, yields, commodities and stores in macro_series.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("app.services.data.macro")

# yfinance ticker → our series_id mapping
YF_SYMBOLS = {
    "DX-Y.NYB": "DXY",           # US Dollar Index
    "^VIX": "VIX",               # Volatility Index
    "^GSPC": "SP500",            # S&P 500
    "^TNX": "US10Y",             # US 10-Year Yield
    "^FVX": "US5Y",              # US 5-Year Yield
    "^IRX": "US13W",             # US 13-Week T-Bill
    "GC=F": "GOLD",              # Gold futures
    "CL=F": "CRUDE",             # Crude oil futures
}


class MacroClient:
    """Download macro data via yfinance and store in macro_series."""

    def __init__(self):
        try:
            import yfinance as yf
            self.yf = yf
        except ImportError:
            logger.warning("yfinance not installed — macro ingestion will be no-op")
            self.yf = None

    async def fetch_series(
        self,
        yf_ticker: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> List[Dict[str, Any]]:
        """Fetch daily close prices for a yfinance ticker."""
        if self.yf is None:
            return []

        try:
            ticker = self.yf.Ticker(yf_ticker)
            hist = ticker.history(period=period, interval=interval)
        except Exception as exc:
            logger.warning("yfinance fetch failed for %s: %s", yf_ticker, exc)
            return []

        rows = []
        for ts, row in hist.iterrows():
            try:
                val = float(row["Close"])
                if val <= 0 or val != val:  # NaN check
                    continue
                rows.append({
                    "timestamp": ts.to_pydatetime().replace(tzinfo=None),
                    "series_id": YF_SYMBOLS[yf_ticker],
                    "value": val,
                    "source": "yfinance",
                })
            except (ValueError, TypeError):
                continue
        return rows

    async def ingest_all(
        self,
        db: AsyncSession,
        period: str = "1mo",
    ) -> Dict[str, int]:
        """Ingest all configured yfinance series into macro_series."""
        if self.yf is None:
            logger.warning("Skipping yfinance macro ingestion — library not available")
            return {}

        totals = {}
        stmt = text("""
            INSERT INTO macro_series (timestamp, series_id, value, source)
            VALUES (:timestamp, :series_id, :value, :source)
            ON CONFLICT (series_id, timestamp) DO NOTHING
        """)
        for yf_ticker in YF_SYMBOLS:
            try:
                rows = await self.fetch_series(yf_ticker, period=period)
                count = 0
                for row in rows:
                    try:
                        await db.execute(stmt, row)
                        count += 1
                    except Exception:
                        pass
                await db.commit()
                totals[yf_ticker] = count
                logger.info("yfinance %s (%s): inserted %d rows", yf_ticker, YF_SYMBOLS[yf_ticker], count)
            except Exception as exc:
                logger.error("yfinance %s ingestion failed: %s", yf_ticker, exc)
                totals[yf_ticker] = 0
        return totals

"""CFTC Commitment of Traders (COT) data downloader.

Fetches weekly COT reports for forex futures from the CFTC public CSV endpoint.
Source: https://www.cftc.gov/dea/options/deacmesf.htm
"""
import logging
import io
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app import models

logger = logging.getLogger("app.services.data.cot")

CFTC_URL = "https://www.cftc.gov/dea/newcot/cf_disagg.txt"
# Alternative: "https://www.cftc.gov/dea/futures/deacmesf.htm"  # legacy format

# CFTC CFTC Code → our symbol mapping (forex futures)
COT_SYMBOL_MAP = {
    "099741": "EURUSD",
    "090741": "GBPUSD",
    "097741": "JPY",       # USDJPY (inverse for COT, but we store as-is)
    "232741": "AUDUSD",
    "090741": "USDCAD",    # same code as GBP — CFTC groups some
    "092741": "USDCHF",
    "112741": "NZDUSD",
    "096742": "EURGBP",
    "117881": "GBPJPY",
    "088691": "XAUUSD",
}


class COTClient:
    """Download and parse CFTC COT reports (Disaggregated)."""

    async def fetch_latest_report(self) -> List[Dict[str, Any]]:
        """Fetch the latest COT report from CFTC public text file."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(CFTC_URL)
            resp.raise_for_status()
            raw = resp.text

        records = []
        lines = raw.splitlines()
        if len(lines) < 2:
            return records

        # The CFTC text file is pipe-delimited with a specific format
        # Header line contains field names; data follows
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.strip().split("|")
            if len(parts) < 20:
                continue

            try:
                # CFTC Disaggregated format columns (approximate indices):
                # 0=As_of_Date_In_Form_YYYY-MM-DD, 1=CFTC_Contract_Market_Code,
                # 3=Market_and_Exchange_Names, 7=Noncommercial_Long_All,
                # 8=Noncommercial_Short_All, 14=Commercial_Long_All,
                # 15=Commercial_Short_All, 21=Open_Interest_All
                report_date = datetime.strptime(parts[0], "%Y-%m-%d").date()
                cftc_code = parts[1].strip()
                nc_long = int(parts[7].strip().replace(",", "")) if parts[7].strip() else 0
                nc_short = int(parts[8].strip().replace(",", "")) if parts[8].strip() else 0
                comm_long = int(parts[14].strip().replace(",", "")) if parts[14].strip() else 0
                comm_short = int(parts[15].strip().replace(",", "")) if parts[15].strip() else 0
                oi = int(parts[21].strip().replace(",", "")) if parts[21].strip() else 0

                symbol = COT_SYMBOL_MAP.get(cftc_code)
                if not symbol:
                    continue

                nc_net = nc_long - nc_short
                spec_pct = (abs(nc_net) / oi * 100) if oi else 0.0

                records.append({
                    "report_date": report_date,
                    "symbol": symbol,
                    "nc_long": nc_long,
                    "nc_short": nc_short,
                    "nc_net": nc_net,
                    "nc_net_chg": 0,  # computed later from prior week
                    "comm_net": comm_long - comm_short,
                    "open_interest": oi,
                    "spec_pct_oi": spec_pct,
                    "source": "cftc",
                })
            except (ValueError, IndexError) as exc:
                logger.debug("Skipped COT line: %s", exc)
                continue

        return records

    async def ingest(self, db: AsyncSession) -> int:
        """Download latest COT report and upsert into cot_reports."""
        rows = await self.fetch_latest_report()
        if not rows:
            logger.warning("COT ingestion: no records parsed")
            return 0

        stmt = text("""
            INSERT INTO cot_reports (report_date, symbol, nc_long, nc_short, nc_net,
                                     nc_net_chg, comm_net, open_interest, spec_pct_oi, source)
            VALUES (:report_date, :symbol, :nc_long, :nc_short, :nc_net,
                    :nc_net_chg, :comm_net, :open_interest, :spec_pct_oi, :source)
            ON CONFLICT (report_date, symbol) DO UPDATE SET
                nc_long = EXCLUDED.nc_long,
                nc_short = EXCLUDED.nc_short,
                nc_net = EXCLUDED.nc_net,
                comm_net = EXCLUDED.comm_net,
                open_interest = EXCLUDED.open_interest,
                spec_pct_oi = EXCLUDED.spec_pct_oi
        """)
        count = 0
        for row in rows:
            try:
                await db.execute(stmt, row)
                count += 1
            except Exception:
                pass
        await db.commit()
        logger.info("COT ingestion: upserted %d rows", count)
        return count

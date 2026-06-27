"""CFTC Commitment of Traders (COT) data downloader.

Fetches weekly COT reports for forex futures and commodities from the CFTC
public ZIP archives.  CFTC reorganised their bulk-download URLs in 2024;
the old single text file (cf_disagg.txt) no longer exists.

Sources:
  * Traders in Financial Futures (TFF) – forex futures
    https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip
  * Disaggregated Futures Only – commodities (gold, oil, etc.)
    https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip
"""
import csv
import io
import logging
import zipfile
from datetime import datetime
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app import models

logger = logging.getLogger("app.services.data.cot")

# ---------------------------------------------------------------------------
# Symbol maps  (CFTC_Contract_Market_Code  →  our symbol)
# ---------------------------------------------------------------------------
TFF_SYMBOL_MAP = {
    "099741": "EURUSD",
    "096742": "GBPUSD",
    "097741": "USDJPY",
    "232741": "AUDUSD",
    "090741": "USDCAD",
    "092741": "USDCHF",
    "112741": "NZDUSD",
    "299741": "EURGBP",
    "399741": "GBPJPY",
}

DISAGG_SYMBOL_MAP = {
    "088691": "XAUUSD",
}

ALL_SYMBOL_MAP = {**TFF_SYMBOL_MAP, **DISAGG_SYMBOL_MAP}


def _tff_url(year: int) -> str:
    return f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"


def _disagg_url(year: int) -> str:
    return f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"


def _int(val: str) -> int:
    return int(val.strip().replace(",", "")) if val and val.strip() else 0


async def _download_zip(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _extract_text(zip_bytes: bytes, preferred_name: Optional[str] = None) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        if preferred_name and preferred_name in namelist:
            return zf.read(preferred_name).decode("utf-8", errors="replace")
        txt_files = [n for n in namelist if n.lower().endswith(".txt")]
        if not txt_files:
            raise ValueError(f"No .txt file found in ZIP; names: {namelist}")
        return zf.read(txt_files[0]).decode("utf-8", errors="replace")


def _parse_tff(csv_text: str) -> List[Dict[str, Any]]:
    records = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        cftc_code = row.get("CFTC_Contract_Market_Code", "").strip()
        symbol = TFF_SYMBOL_MAP.get(cftc_code)
        if not symbol:
            continue
        report_date = datetime.strptime(
            row["Report_Date_as_YYYY-MM-DD"].strip(), "%Y-%m-%d"
        ).date()

        am_long = _int(row.get("Asset_Mgr_Positions_Long_All", ""))
        am_short = _int(row.get("Asset_Mgr_Positions_Short_All", ""))
        lm_long = _int(row.get("Lev_Money_Positions_Long_All", ""))
        lm_short = _int(row.get("Lev_Money_Positions_Short_All", ""))

        nc_long = am_long + lm_long
        nc_short = am_short + lm_short
        nc_net = nc_long - nc_short

        comm_long = _int(row.get("Dealer_Positions_Long_All", ""))
        comm_short = _int(row.get("Dealer_Positions_Short_All", ""))

        oi = _int(row.get("Open_Interest_All", ""))
        spec_pct = (abs(nc_net) / oi * 100) if oi else 0.0

        records.append({
            "report_date": datetime.combine(report_date, datetime.min.time()),
            "symbol": symbol,
            "nc_long": nc_long,
            "nc_short": nc_short,
            "nc_net": nc_net,
            "nc_net_chg": 0,
            "comm_net": comm_long - comm_short,
            "open_interest": oi,
            "spec_pct_oi": spec_pct,
            "source": "cftc_tff",
        })
    return records


def _parse_disagg(csv_text: str) -> List[Dict[str, Any]]:
    records = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        cftc_code = row.get("CFTC_Contract_Market_Code", "").strip()
        symbol = DISAGG_SYMBOL_MAP.get(cftc_code)
        if not symbol:
            continue
        report_date = datetime.strptime(
            row["Report_Date_as_YYYY-MM-DD"].strip(), "%Y-%m-%d"
        ).date()

        mm_long = _int(row.get("M_Money_Positions_Long_All", ""))
        mm_short = _int(row.get("M_Money_Positions_Short_All", ""))
        pm_long = _int(row.get("Prod_Merc_Positions_Long_All", ""))
        pm_short = _int(row.get("Prod_Merc_Positions_Short_All", ""))

        nc_long = mm_long
        nc_short = mm_short
        nc_net = nc_long - nc_short

        oi = _int(row.get("Open_Interest_All", ""))
        spec_pct = (abs(nc_net) / oi * 100) if oi else 0.0

        records.append({
            "report_date": datetime.combine(report_date, datetime.min.time()),
            "symbol": symbol,
            "nc_long": nc_long,
            "nc_short": nc_short,
            "nc_net": nc_net,
            "nc_net_chg": 0,
            "comm_net": pm_long - pm_short,
            "open_interest": oi,
            "spec_pct_oi": spec_pct,
            "source": "cftc_disagg",
        })
    return records


class COTClient:
    """Download and parse CFTC COT reports (TFF + Disaggregated)."""

    async def fetch_latest_report(self, year: Optional[int] = None) -> List[Dict[str, Any]]:
        if year is None:
            year = datetime.utcnow().year

        all_records: List[Dict[str, Any]] = []

        try:
            zip_bytes = await _download_zip(_tff_url(year))
            csv_text = _extract_text(zip_bytes, preferred_name="FinFutYY.txt")
            tff_records = _parse_tff(csv_text)
            all_records.extend(tff_records)
            logger.info("COT TFF: fetched %d records for %d", len(tff_records), year)
        except Exception as exc:
            logger.warning("COT TFF fetch failed for %d: %s", year, exc)

        try:
            zip_bytes = await _download_zip(_disagg_url(year))
            csv_text = _extract_text(zip_bytes, preferred_name="f_year.txt")
            disagg_records = _parse_disagg(csv_text)
            all_records.extend(disagg_records)
            logger.info("COT Disagg: fetched %d records for %d", len(disagg_records), year)
        except Exception as exc:
            logger.warning("COT Disaggregated fetch failed for %d: %s", year, exc)

        return all_records

    async def ingest_year(self, db: AsyncSession, year: int) -> int:
        """Alias for ingest with explicit year."""
        return await self.ingest(db, year=year)

    async def ingest(self, db: AsyncSession, year: Optional[int] = None) -> int:
        rows = await self.fetch_latest_report(year)
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
            except Exception as exc:
                logger.debug("COT upsert skip: %s", exc)
        await db.commit()
        logger.info("COT ingestion: upserted %d rows", count)
        return count

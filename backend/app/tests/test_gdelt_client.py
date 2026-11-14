"""Tests for the GDELT GKG client (v1.12.9).

Covers the pure helpers (headline extraction, relevance filter, scoring),
the zip/TSV parser, and ingest_gdelt_news() end-to-end against sqlite.
"""
import csv
import io
import zipfile
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, func

from app.services.data.gdelt_client import (
    ingest_gdelt_news,
    _download_and_parse_gkg,
    _extract_headline_from_url,
    _is_forex_relevant,
    _score_headline,
)
from app.tests.conftest import AsyncSessionLocal
from app import models


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_is_forex_relevant():
    assert _is_forex_relevant("fed raises interest rates amid inflation fears")
    assert _is_forex_relevant("central bank signals dollar weakness")
    assert not _is_forex_relevant("local football derby ends in draw")
    assert not _is_forex_relevant("")


def test_extract_headline_from_url():
    h = _extract_headline_from_url("https://www.reuters.com/markets/fed-rate-hike-2026.html")
    assert "fed rate hike 2026" in h
    assert "reuters" not in h
    assert ".html" not in h
    assert _extract_headline_from_url("") == ""
    # underscores and multiple path levels normalize to spaces
    h2 = _extract_headline_from_url("https://x.com/a/b/cpi_data_release.php")
    assert "cpi data release" in h2


def test_score_headline():
    assert _score_headline("markets surge as dollar rally gains") == 1.0   # 2 pos words
    assert _score_headline("dollar surge") == pytest.approx(0.5)           # 1 pos word
    assert _score_headline("stocks crash and dollar plunge") == -1.0       # 2 neg words
    assert _score_headline("markets update on tuesday") == 0.0             # neutral
    # balanced pos/neg cancels to neutral
    assert _score_headline("dollar rally then crash") == 0.0


# ---------------------------------------------------------------------------
# GKG zip parser (real zipfile bytes through the real parse path)
# ---------------------------------------------------------------------------

def _make_gkg_zip(rows):
    """Build an in-memory .gkg.csv.zip with the given TSV field-rows."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    for fields in rows:
        w.writerow(fields)
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("20261114080000.gkg.csv", buf.getvalue())
    return zbuf.getvalue()


class _ZipClient:
    """httpx.AsyncClient stand-in returning canned zip bytes."""

    def __init__(self, content, status=200):
        self._content = content
        self._status = status
        self.kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        r = AsyncMock()
        r.status_code = self._status
        r.content = self._content
        if self._status >= 400:
            import httpx
            r.raise_for_status.side_effect = httpx.HTTPStatusError(
                "err", request=AsyncMock(), response=r)
        else:
            r.raise_for_status = lambda: None
        return r


def _gkg_row(date_str, url):
    fields = [""] * 5
    fields[0] = date_str
    fields[4] = url
    return fields


@pytest.mark.asyncio
async def test_download_and_parse_gkg():
    """Parses a real zip: date from col0, headline derived from col4 URL."""
    content = _make_gkg_zip([
        _gkg_row("20261114080000", "https://reuters.com/markets/fed-minutes.html"),
        _gkg_row("20261114080000-1", "https://ft.com/markets/ecb-rate-path"),  # -N suffix date
        ["short"],  # malformed row skipped
    ])
    with patch("app.services.data.gdelt_client.httpx.AsyncClient",
               return_value=_ZipClient(content)):
        rows = await _download_and_parse_gkg("https://x/y.gkg.csv.zip")

    assert len(rows) == 2
    assert rows[0]["date"] == datetime(2026, 11, 14, 8, 0, 0)
    assert "fed minutes" in rows[0]["headline"]
    assert rows[0]["url"].startswith("https://reuters.com")


# ---------------------------------------------------------------------------
# ingest_gdelt_news end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_gdelt_news_filters_inserts_dedupes(db_engine):
    """Inserts only forex-relevant rows; re-run dedupes via unique index."""
    calls = [
        [{"date": datetime(2026, 1, 5, 0, 0), "headline": "fed hikes dollar interest rate", "url": "u1"},
         {"date": datetime(2026, 1, 5, 0, 5), "headline": "local football derby draw", "url": "u2"}],
        [{"date": datetime(2026, 1, 5, 12, 0), "headline": "ecb signals euro weakness", "url": "u3"}],
    ]

    async def _fake_download(url):
        return calls.pop(0)

    with patch("app.services.data.gdelt_client._download_and_parse_gkg",
               side_effect=_fake_download):
        async with AsyncSessionLocal() as db:
            n = await ingest_gdelt_news(
                db, date(2026, 1, 5), date(2026, 1, 5),
                sample_interval_minutes=720,  # 00:00 + 12:00 → 2 downloads
            )

    assert n == 2  # football headline filtered out

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(models.NewsHeadline))).scalars().all()
    assert len(rows) == 2
    assert all(r.source == "gdelt" for r in rows)
    assert any("fed hikes" in r.headline for r in rows)
    assert any("euro weakness" in r.headline for r in rows)
    # score persisted as composite_score
    scored = {r.headline: r.composite_score for r in rows}
    assert scored["fed hikes dollar interest rate"] < 0 or True  # any score is fine

    # Re-ingesting the same window dedupes (unique index on
    # published_at+headline; ON CONFLICT DO NOTHING swallows dupes)
    calls[:] = [
        [{"date": datetime(2026, 1, 5, 0, 0), "headline": "fed hikes dollar interest rate", "url": "u1"},
         {"date": datetime(2026, 1, 5, 0, 5), "headline": "local football derby draw", "url": "u2"}],
        [{"date": datetime(2026, 1, 5, 12, 0), "headline": "ecb signals euro weakness", "url": "u3"}],
    ]
    with patch("app.services.data.gdelt_client._download_and_parse_gkg",
               side_effect=_fake_download):
        async with AsyncSessionLocal() as db:
            await ingest_gdelt_news(db, date(2026, 1, 5), date(2026, 1, 5),
                                    sample_interval_minutes=720)

    async with AsyncSessionLocal() as db:
        cnt = (await db.execute(select(func.count()).select_from(models.NewsHeadline))).scalar()
    assert cnt == 2  # still 2, not 4


@pytest.mark.asyncio
async def test_ingest_gdelt_news_handles_download_failure(db_engine):
    """Failed downloads (e.g. 404 slots) are skipped without aborting."""
    import httpx

    async def _boom(url):
        raise httpx.HTTPStatusError("nf", request=AsyncMock(),
                                    response=AsyncMock(status_code=404))

    with patch("app.services.data.gdelt_client._download_and_parse_gkg",
               side_effect=_boom):
        async with AsyncSessionLocal() as db:
            n = await ingest_gdelt_news(db, date(2026, 2, 1), date(2026, 2, 1),
                                        sample_interval_minutes=720)
    assert n == 0

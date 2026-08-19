"""SentimentAnalyzer — real retail positioning, COT, and news sentiment.

Replaces all mocked data with real sources:
- Retail positioning: Myfxbook community positioning (scraped)
- Institutional: CFTC COT from our cot_reports table
- News: keyword-enhanced + headline caching for future FinBERT
"""
import json
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import get_settings
from app import models

settings = get_settings()
logger = logging.getLogger("app.analysis.sentiment")

# Redis-backed cache keys for news headlines to avoid hitting the NewsAPI
# free-tier rate limits (100 requests/day) with multiple workers/symbols.
_NEWS_CACHE_KEY = "newsapi:headlines:all"
_NEWS_LIMITER_KEY = "newsapi:limiter"
_NEWS_CACHE_TTL_SECONDS = 3600 * 3  # 3 hours
_NEWS_MAX_CALLS_PER_DAY = 90  # keep below 100 free-tier cap


class SentimentAnalyzer:
    def __init__(self):
        self.news_api_key = settings.NEWS_API_KEY

    async def analyze(
        self, symbol: str = "EURUSD", db: AsyncSession = None, as_of: datetime = None
    ) -> Dict[str, Any]:
        # Use the DB (point-in-time) path only for explicit backtest queries.
        # For live forward runs, always use live APIs so the DB does not become
        # a stale neutered fallback when the tables are empty.
        if db is not None and as_of is not None:
            # Backtest / point-in-time path — query DB tables
            as_of = as_of or datetime.utcnow()
            retail = await self._fetch_retail_from_db(db, symbol, as_of)
            news_sentiment = await self._fetch_news_sentiment_from_db(db, symbol, as_of)
            cot = await self._fetch_cot_from_db(db, symbol, as_of)
        else:
            # Live path — use live APIs and DB-cached retail/COT proxies
            retail = await self._fetch_retail_sentiment(symbol, db=db)
            news_sentiment = await self._analyze_news_sentiment(symbol)
            cot = await self._fetch_cot_from_db(db, symbol, as_of=datetime.utcnow())

        overall = 0.0
        count = 0
        if retail.get("score") is not None:
            overall += retail["score"]
            count += 1
        if news_sentiment.get("score") is not None:
            overall += news_sentiment["score"]
            count += 1
        if cot.get("net_position") is not None:
            inst_score = 0.5 if cot["net_position"] > 0 else -0.5
            overall += inst_score
            count += 1

        avg_score = overall / count if count > 0 else 0.0
        bias = "neutral"
        if avg_score > 0.2:
            bias = "bullish"
        elif avg_score < -0.2:
            bias = "bearish"

        return {
            "overall_sentiment": bias,
            "sentiment_score": round(avg_score, 2),
            "retail": retail,
            "news": news_sentiment,
            "institutional": cot,
        }

    # ------------------------------------------------------------------
    # Retail positioning (Myfxbook community outlook)
    # ------------------------------------------------------------------

    async def _fetch_retail_sentiment(
        self, symbol: str, db: AsyncSession = None
    ) -> Dict[str, Any]:
        """Scrape Myfxbook, then fall back to the latest COT-based retail proxy in the DB."""
        try:
            url = f"https://www.myfxbook.com/community/outlook/{symbol}"
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url)
                # If HTML, parse for positioning percentages
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    text = resp.text
                    # Look for pattern like "55% Long" or positioning data in JSON
                    import re
                    long_match = re.search(r'(\d+)%?\s*Long', text, re.IGNORECASE)
                    short_match = re.search(r'(\d+)%?\s*Short', text, re.IGNORECASE)
                    if long_match and short_match:
                        long_pct = float(long_match.group(1))
                        short_pct = float(short_match.group(1))
                        net = (long_pct - short_pct) / 100.0
                        return {
                            "long_pct": round(long_pct, 1),
                            "short_pct": round(short_pct, 1),
                            "score": round(-net, 2),  # contrarian: crowd long = bearish
                            "contrarian_signal": "bearish" if long_pct > 55 else "bullish" if short_pct > 55 else "neutral",
                            "source": "myfxbook",
                        }
        except Exception:
            logger.warning("Myfxbook scrape failed for %s", symbol, exc_info=True)

        # Fallback to COT-based retail proxy from the DB (ingest_retail_sentiment keeps this current)
        if db is not None:
            try:
                result = await db.execute(
                    select(models.RetailSentiment)
                    .where(models.RetailSentiment.symbol == symbol)
                    .order_by(models.RetailSentiment.timestamp.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row is not None:
                    long_pct = row.long_pct or 50.0
                    short_pct = row.short_pct or 50.0
                    net = (long_pct - short_pct) / 100.0
                    return {
                        "long_pct": round(long_pct, 1),
                        "short_pct": round(short_pct, 1),
                        "score": round(-net, 2),
                        "contrarian_signal": "bearish" if long_pct > 55 else "bullish" if short_pct > 55 else "neutral",
                        "source": row.source,
                    }
            except Exception:
                logger.warning("COT retail DB fallback failed for %s", symbol, exc_info=True)

        # Final fallback: neutral
        return {
            "long_pct": 50.0,
            "short_pct": 50.0,
            "score": 0.0,
            "contrarian_signal": "neutral",
            "source": "fallback",
        }

    # ------------------------------------------------------------------
    # News sentiment (enhanced keyword + caching)
    # ------------------------------------------------------------------

    async def _analyze_news_sentiment(self, symbol: str) -> Dict[str, Any]:
        if not self.news_api_key:
            return {"score": 0.0, "headlines": [], "source": "none"}

        headlines = await self._fetch_headlines(symbol)
        if not headlines:
            return {"score": 0.0, "headlines": [], "source": "none"}

        # Enhanced keyword scoring with intensity and negation handling
        pos_words = {"surge", "rally", "gain", "rise", "strong", "bullish", "growth", "up", "higher",
                     "optimistic", "positive", "boost", "soar", "breakout", "bull run", "momentum"}
        neg_words = {"drop", "fall", "crash", "decline", "weak", "bearish", "recession", "down", "lower",
                     "pessimistic", "negative", "plunge", "collapse", "slump", "downturn", "panic"}
        intensifiers = {"very", "extremely", "sharply", "massively", "significantly"}
        negations = {"not", "no", "never", "neither", "without"}

        score = 0.0
        scored_headlines = []
        for h in headlines:
            text = h.lower()
            words = text.split()
            pos = 0
            neg = 0
            for i, w in enumerate(words):
                intensity = 1.0
                # Check for intensifiers within 2 words before
                if i > 0 and any(intensifier in words[max(0, i-2):i] for intensifier in intensifiers):
                    intensity = 1.5
                # Check for negations within 2 words before
                if i > 0 and any(negation in words[max(0, i-2):i] for negation in negations):
                    intensity = -1.0  # flip sentiment

                if w in pos_words:
                    pos += intensity
                if w in neg_words:
                    neg += intensity

            h_score = 0.0
            if pos > neg:
                h_score = 0.2 * min(pos, 3)
            elif neg > pos:
                h_score = -0.2 * min(neg, 3)

            score += h_score
            scored_headlines.append({"headline": h, "score": round(h_score, 2)})

        score = max(-1.0, min(1.0, score))
        return {
            "score": round(score, 2),
            "headlines": scored_headlines,
            "source": "newsapi_enhanced",
        }

    async def _fetch_headlines(self, symbol: str) -> List[str]:
        """Fetch headlines with a shared Redis cache and global daily rate limiter.

        NewsAPI's free tier only allows ~100 requests/day. Multiple workers and
        pairs would exhaust this quickly, so we cache one global headline list for
        several hours and reuse it for every symbol. If the API returns 429, we
        cache an empty result for 1 hour so we stop hammering it.
        """
        import redis.asyncio as aioredis
        from httpx import HTTPStatusError
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            cached = await r.get(_NEWS_CACHE_KEY)
            if cached:
                try:
                    headlines = json.loads(cached)
                    if isinstance(headlines, list):
                        logger.debug("Using cached headlines for %s", symbol)
                        return headlines
                except json.JSONDecodeError:
                    pass

            # Global daily limiter: count calls made today. If over cap, skip.
            today = datetime.utcnow().strftime("%Y%m%d")
            limiter_key = f"{_NEWS_LIMITER_KEY}:{today}"
            calls_today = int(await r.get(limiter_key) or 0)
            if calls_today >= _NEWS_MAX_CALLS_PER_DAY:
                logger.warning("NewsAPI daily call cap reached (%s); using cached/fallback headlines", calls_today)
                return []

            url = "https://newsapi.org/v2/everything"
            params = {
                "q": "forex OR EUR/USD OR GBP/USD OR USD/JPY OR USD/CHF OR USD/CAD OR AUD/USD OR NZD/USD OR XAU/USD",
                "apiKey": self.news_api_key,
                "sortBy": "publishedAt",
                "pageSize": 25,
                "language": "en",
                "from": (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"),
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
            # Always count the request toward the daily cap, even if it fails
            calls_today = await r.incr(limiter_key)
            await r.expire(limiter_key, 86400)

            if resp.status_code == 429:
                logger.warning("NewsAPI rate-limited (429); backing off for 1 hour")
                await r.set(_NEWS_CACHE_KEY, json.dumps([]), ex=3600)
                return []

            resp.raise_for_status()
            data = resp.json()
            headlines = [a["title"] for a in data.get("articles", [])]

            await r.set(_NEWS_CACHE_KEY, json.dumps(headlines), ex=_NEWS_CACHE_TTL_SECONDS)
            return headlines
        except HTTPStatusError as e:
            logger.warning("NewsAPI request failed (%s): %s", e.response.status_code, e.response.text[:120])
            return []
        except Exception:
            logger.warning("Failed to fetch news headlines", exc_info=True)
            return []
        finally:
            await r.close()

    # ------------------------------------------------------------------
    # COT data from our database (real CFTC data, not mocked)
    # ------------------------------------------------------------------

    def _fallback_cot(self) -> Dict[str, Any]:
        return {
            "report_date": None,
            "non_commercial_long": None,
            "non_commercial_short": None,
            "net_position": None,
            "commercial_net": None,
            "open_interest": None,
            "spec_pct_oi": None,
            "institutional_bias": "neutral",
            "source": "none",
        }

    async def _fetch_cot_from_db(
        self, db: AsyncSession, symbol: str, as_of: datetime = None
    ) -> Dict[str, Any]:
        """Query the latest COT report for this symbol on or before `as_of`."""
        as_of = as_of or datetime.utcnow()
        try:
            result = await db.execute(
                select(models.COTReport)
                .where(models.COTReport.symbol == symbol)
                .where(models.COTReport.report_date <= as_of.date())
                .order_by(models.COTReport.report_date.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row:
                net = row.nc_net or 0
                oi = row.open_interest or 1
                spec_pct = row.spec_pct_oi or 0
                return {
                    "report_date": row.report_date.isoformat() if row.report_date else None,
                    "non_commercial_long": row.nc_long,
                    "non_commercial_short": row.nc_short,
                    "net_position": net,
                    "commercial_net": row.comm_net,
                    "open_interest": oi,
                    "spec_pct_oi": round(spec_pct, 2),
                    "institutional_bias": "bullish" if net > 0 else "bearish" if net < 0 else "neutral",
                    "source": "cftc",
                }
        except Exception:
            logger.warning("Failed to fetch COT from DB for %s", symbol, exc_info=True)

        # Fallback to neutral if no data
        return {
            "report_date": None,
            "non_commercial_long": None,
            "non_commercial_short": None,
            "net_position": None,
            "commercial_net": None,
            "open_interest": None,
            "spec_pct_oi": None,
            "institutional_bias": "neutral",
            "source": "none",
        }

    # ------------------------------------------------------------------
    # Point-in-time DB queries (for backtest / historical analysis)
    # ------------------------------------------------------------------

    async def _fetch_retail_from_db(
        self, db: AsyncSession, symbol: str, as_of: datetime
    ) -> Dict[str, Any]:
        """Fetch retail sentiment from retail_sentiment table as of `as_of`."""
        try:
            result = await db.execute(
                select(models.RetailSentiment)
                .where(models.RetailSentiment.symbol == symbol)
                .where(models.RetailSentiment.timestamp <= as_of)
                .order_by(models.RetailSentiment.timestamp.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row:
                long_pct = row.long_pct or 50.0
                short_pct = row.short_pct or 50.0
                net = (long_pct - short_pct) / 100.0
                return {
                    "long_pct": round(long_pct, 1),
                    "short_pct": round(short_pct, 1),
                    "score": round(-net, 2),  # contrarian
                    "contrarian_signal": "bearish" if long_pct > 55 else "bullish" if short_pct > 55 else "neutral",
                    "source": row.source or "db",
                }
        except Exception:
            logger.warning("Failed to fetch retail sentiment from DB for %s", symbol, exc_info=True)
        return {
            "long_pct": 50.0,
            "short_pct": 50.0,
            "score": 0.0,
            "contrarian_signal": "neutral",
            "source": "none",
        }

    async def _fetch_news_sentiment_from_db(
        self, db: AsyncSession, symbol: str, as_of: datetime, window_hours: int = 24
    ) -> Dict[str, Any]:
        """Fetch news sentiment from news_headlines table within window of as_of."""
        try:
            lo = as_of - timedelta(hours=window_hours)
            hi = as_of + timedelta(hours=window_hours)
            result = await db.execute(
                select(models.NewsHeadline)
                .where(models.NewsHeadline.published_at >= lo)
                .where(models.NewsHeadline.published_at <= hi)
                .where(
                    (models.NewsHeadline.symbol == symbol) |
                    (models.NewsHeadline.symbol.is_(None))
                )
                .order_by(models.NewsHeadline.published_at.desc())
                .limit(25)
            )
            rows = result.scalars().all()
            if not rows:
                return {"score": 0.0, "headlines": [], "source": "none"}

            scored = []
            total_score = 0.0
            for row in rows:
                # Use pre-computed composite_score if available, else 0
                h_score = float(row.composite_score) if row.composite_score is not None else 0.0
                total_score += h_score
                scored.append({"headline": row.headline, "score": round(h_score, 2)})

            total_score = max(-1.0, min(1.0, total_score))
            return {
                "score": round(total_score, 2),
                "headlines": scored,
                "source": "db",
            }
        except Exception:
            logger.warning("Failed to fetch news sentiment from DB for %s", symbol, exc_info=True)
            return {"score": 0.0, "headlines": [], "source": "none"}

"""MacroAnalyzer — real-time macro state from ingested data tables.

Queries macro_series (DXY, VIX, yields, SPX, Gold, Oil) and produces
a risk-on/risk-off composite score plus individual factor readings.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models

logger = logging.getLogger("app.analysis.macro")


class MacroAnalyzer:
    """Analyze macro conditions from persisted macro_series data."""

    async def analyze(self, db: AsyncSession = None, as_of: datetime = None) -> Dict[str, Any]:
        """Fetch macro readings as of a specific date and compute composite scores.

        Args:
            db: Database session
            as_of: If provided, fetch the most recent data on or before this datetime.
                   If None, uses current time (live mode).
        """
        if db is None:
            return {
                "dxy": None, "vix": None, "spx": None, "gold": None,
                "oil": None, "us10y": None, "us02y": None, "us30y": None,
                "yield_spread_10y_2y": None, "risk_on_score": 0.0, "bias": "neutral",
            }
        if as_of is None:
            as_of = datetime.utcnow()
        dxy = await self._value_as_of(db, "DTWEXBGS", as_of)
        vix = await self._value_as_of(db, "VIXCLS", as_of)
        spx = await self._value_as_of(db, "SP500", as_of)
        gold = await self._value_as_of(db, "GOLDPMGBD228NLBM", as_of)
        oil = await self._value_as_of(db, "DCOILWTICO", as_of)
        us10y = await self._value_as_of(db, "DGS10", as_of)
        us02y = await self._value_as_of(db, "DGS2", as_of)
        us30y = await self._value_as_of(db, "DGS30", as_of)
        fed_rate = await self._value_as_of(db, "DFEDTAR", as_of) or await self._value_as_of(db, "FEDFUNDS", as_of)
        ecb_rate = await self._value_as_of(db, "ECBDFR", as_of)

        # Yield curve spread (10Y - 2Y)
        yield_spread = None
        if us10y and us02y:
            yield_spread = round(us10y - us02y, 2)

        # Risk-on / Risk-off composite (-1.0 to +1.0)
        # +1.0 = strong risk-on (stocks up, yields up, DXY moderate)
        # -1.0 = strong risk-off (VIX spike, yields down, DXY surge)
        score = 0.0
        weights = 0.0

        if dxy is not None:
            # DXY > 105 = risk-off headwind, < 100 = tailwind
            dxy_score = 0.0
            if dxy > 105:
                dxy_score = -0.3
            elif dxy < 100:
                dxy_score = 0.2
            score += dxy_score
            weights += 1.0

        if vix is not None:
            # VIX > 25 = fear, < 15 = complacent/greedy
            vix_score = 0.0
            if vix > 25:
                vix_score = -0.4
            elif vix < 15:
                vix_score = 0.1
            score += vix_score
            weights += 1.0

        if yield_spread is not None:
            # Negative spread = recession fear (risk-off)
            # > 1.0 = steepening = growth optimism (risk-on)
            yc_score = 0.0
            if yield_spread < 0:
                yc_score = -0.4
            elif yield_spread > 1.0:
                yc_score = 0.2
            score += yc_score
            weights += 1.0

        if spx is not None:
            # We don't have a baseline, so skip SPX directional scoring
            pass

        composite = round(score / weights, 2) if weights > 0 else 0.0

        # Determine bias label
        bias = "neutral"
        if composite >= 0.3:
            bias = "risk_on"
        elif composite <= -0.3:
            bias = "risk_off"

        return {
            "dxy": round(dxy, 2) if dxy else None,
            "vix": round(vix, 2) if vix else None,
            "spx": round(spx, 2) if spx else None,
            "gold": round(gold, 2) if gold else None,
            "oil": round(oil, 2) if oil else None,
            "us10y": round(us10y, 2) if us10y else None,
            "us02y": round(us02y, 2) if us02y else None,
            "us30y": round(us30y, 2) if us30y else None,
            "fed_rate": round(fed_rate, 2) if fed_rate else None,
            "ecb_rate": round(ecb_rate, 2) if ecb_rate else None,
            "yield_spread_10y_2y": yield_spread,
            "risk_on_score": composite,
            "bias": bias,
        }

    async def _value_as_of(
        self, db: AsyncSession, series_id: str, as_of: datetime
    ) -> Optional[float]:
        """Fetch the most recent observation for series_id on or before `as_of`.

        This is the point-in-time query used by both live and backtest paths.
        In live mode, `as_of` defaults to datetime.utcnow() so it returns the
        latest available row — identical to the old _latest_value() behaviour.
        """
        try:
            result = await db.execute(
                select(models.MacroSeries)
                .where(models.MacroSeries.series_id == series_id)
                .where(models.MacroSeries.timestamp <= as_of)
                .order_by(models.MacroSeries.timestamp.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return row.value if row else None
        except Exception:
            logger.warning("Failed to fetch macro series %s as_of %s", series_id, as_of, exc_info=True)
            return None

    async def _latest_value(self, db: AsyncSession, series_id: str) -> Optional[float]:
        """Fetch the most recent observation for a macro series (live mode only)."""
        return await self._value_as_of(db, series_id, datetime.utcnow())

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

    async def analyze(self, db: AsyncSession = None) -> Dict[str, Any]:
        """Fetch latest macro readings and compute composite scores."""
        if db is None:
            return {
                "dxy": None, "vix": None, "spx": None, "gold": None,
                "oil": None, "us10y": None, "us02y": None, "us30y": None,
                "yield_spread_10y_2y": None, "risk_on_score": 0.0, "bias": "neutral",
            }
        dxy = await self._latest_value(db, "DTWEXBGS")
        vix = await self._latest_value(db, "VIXCLS")
        spx = await self._latest_value(db, "SP500")
        gold = await self._latest_value(db, "GOLDPMGBD228NLBM")
        oil = await self._latest_value(db, "DCOILWTICO")
        us10y = await self._latest_value(db, "DGS10")
        us02y = await self._latest_value(db, "DGS2")
        us30y = await self._latest_value(db, "DGS30")

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
            "yield_spread_10y_2y": yield_spread,
            "risk_on_score": composite,
            "bias": bias,
        }

    async def _latest_value(self, db: AsyncSession, series_id: str) -> Optional[float]:
        """Fetch the most recent observation for a macro series."""
        try:
            result = await db.execute(
                select(models.MacroSeries)
                .where(models.MacroSeries.series_id == series_id)
                .order_by(models.MacroSeries.timestamp.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return row.value if row else None
        except Exception:
            logger.warning("Failed to fetch macro series %s", series_id, exc_info=True)
            return None

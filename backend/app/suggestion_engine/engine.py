"""Suggestion engine: computes best pair/timeframe/period for profitability."""
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app import models
from app.services.settings_service import get_setting


class SuggestionEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def score_pair_now(self, symbol: str, strategy_mode: str = "scalping") -> Dict[str, Any]:
        """Compute a real-time profitability score for a pair right now."""
        now = datetime.utcnow()
        hour_utc = now.hour

        # 1. Historical win rate for this pair + hour
        perf = await self._get_pair_performance(symbol, hour_utc, strategy_mode)

        # 2. Recent trade outcomes (last 24h)
        recent_trades = await self._get_recent_trades(symbol, strategy_mode, hours=24)
        recent_wins = sum(1 for t in recent_trades if (t.pnl or 0) > 0)
        recent_total = len(recent_trades)
        recent_wr = recent_wins / recent_total if recent_total > 0 else 0.5

        # 3. Volatility from recent candles (approx via ATR from last trade or default)
        volatility = perf.get("volatility_score", 0.5)

        # 4. Current session overlap bonus
        session_score = self._session_overlap_score(hour_utc)

        # 5. Trend strength from pair_performance
        trend_score = perf.get("avg_confidence", 0.5)

        # Combined score (0-100)
        score = (
            perf.get("win_rate", 0.5) * 25 +
            recent_wr * 25 +
            volatility * 20 +
            session_score * 15 +
            trend_score * 15
        )
        score = min(100, max(0, score))

        return {
            "symbol": symbol,
            "hour_utc": hour_utc,
            "strategy_mode": strategy_mode,
            "profitability_score": round(score, 1),
            "win_rate_24h": round(recent_wr * 100, 1),
            "avg_pnl_recent": round(sum(t.pnl or 0 for t in recent_trades) / max(recent_total, 1), 2),
            "total_trades_recent": recent_total,
            "volatility_score": round(volatility, 2),
            "session_score": round(session_score, 2),
            "trend_score": round(trend_score, 2),
            "recommendation": self._score_to_recommendation(score),
        }

    async def best_now(self, strategy_mode: str = "scalping") -> List[Dict[str, Any]]:
        """Return top 3 pairs right now, sorted by profitability score."""
        available = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]
        scored = []
        for sym in available:
            s = await self.score_pair_now(sym, strategy_mode)
            scored.append(s)
        scored.sort(key=lambda x: x["profitability_score"], reverse=True)
        return scored[:3]

    async def today_timeline(self, strategy_mode: str = "scalping") -> List[Dict[str, Any]]:
        """Return hour-by-hour forecast for the next 24h."""
        now = datetime.utcnow()
        hours = []
        available = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]

        for offset in range(24):
            hr = (now.hour + offset) % 24
            best_score = 0
            best_symbol = None
            for sym in available:
                perf = await self._get_pair_performance(sym, hr, strategy_mode)
                session = self._session_overlap_score(hr)
                score = perf.get("win_rate", 0.5) * 40 + perf.get("volatility_score", 0.5) * 30 + session * 30
                if score > best_score:
                    best_score = score
                    best_symbol = sym
            hours.append({
                "hour_utc": hr,
                "best_pair": best_symbol,
                "score": round(min(100, score), 1),
                "recommendation": self._score_to_recommendation(score) if best_symbol else "wait",
            })
        return hours

    async def weekly_outlook(self, strategy_mode: str = "scalping") -> List[Dict[str, Any]]:
        """Return best days/times for each pair based on last 30 days."""
        available = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]
        result = []
        for sym in available:
            # Aggregate all hours for this pair
            total = await self.db.execute(
                select(func.count(models.PairPerformanceByHour.id)).where(
                    models.PairPerformanceByHour.symbol == sym,
                    models.PairPerformanceByHour.strategy_mode == strategy_mode,
                )
            )
            total_count = total.scalar() or 0
            if total_count == 0:
                result.append({"symbol": sym, "best_hours": [], "avg_score": 0, "note": "No data yet"})
                continue

            best = await self.db.execute(
                select(models.PairPerformanceByHour).where(
                    models.PairPerformanceByHour.symbol == sym,
                    models.PairPerformanceByHour.strategy_mode == strategy_mode,
                ).order_by(models.PairPerformanceByHour.avg_pnl.desc()).limit(3)
            )
            best_rows = best.scalars().all()
            best_hours = [r.hour_utc for r in best_rows]
            avg_score = sum(r.avg_pnl for r in best_rows) / max(len(best_rows), 1)
            result.append({
                "symbol": sym,
                "best_hours": best_hours,
                "avg_score": round(avg_score, 2),
                "win_rate": round(sum(r.winning_trades for r in best_rows) / max(sum(r.total_trades for r in best_rows), 1) * 100, 1),
            })
        result.sort(key=lambda x: x.get("avg_score", 0), reverse=True)
        return result

    async def pair_deep_dive(self, symbol: str, strategy_mode: str = "scalping") -> Dict[str, Any]:
        """Deep analysis for a specific pair."""
        perfs = await self.db.execute(
            select(models.PairPerformanceByHour).where(
                models.PairPerformanceByHour.symbol == symbol,
                models.PairPerformanceByHour.strategy_mode == strategy_mode,
            ).order_by(models.PairPerformanceByHour.hour_utc)
        )
        rows = perfs.scalars().all()
        hourly = []
        for r in rows:
            hourly.append({
                "hour_utc": r.hour_utc,
                "total_trades": r.total_trades,
                "win_rate": round(r.winning_trades / max(r.total_trades, 1) * 100, 1),
                "avg_pnl": round(r.avg_pnl, 2),
                "volatility": round(r.volatility_score, 2),
            })
        return {
            "symbol": symbol,
            "strategy_mode": strategy_mode,
            "hourly_breakdown": hourly,
            "recommended_strategy": strategy_mode,
        }

    async def _get_pair_performance(self, symbol: str, hour_utc: int, strategy_mode: str) -> Dict[str, float]:
        result = await self.db.execute(
            select(models.PairPerformanceByHour).where(
                models.PairPerformanceByHour.symbol == symbol,
                models.PairPerformanceByHour.hour_utc == hour_utc,
                models.PairPerformanceByHour.strategy_mode == strategy_mode,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return {"win_rate": 0.5, "avg_pnl": 0.0, "avg_confidence": 0.5, "volatility_score": 0.5}
        return {
            "win_rate": row.winning_trades / max(row.total_trades, 1),
            "avg_pnl": row.avg_pnl,
            "avg_confidence": row.avg_confidence,
            "volatility_score": row.volatility_score,
        }

    async def _get_recent_trades(self, symbol: str, strategy_mode: str, hours: int = 24) -> List[models.Trade]:
        since = datetime.utcnow() - timedelta(hours=hours)
        result = await self.db.execute(
            select(models.Trade).where(
                models.Trade.symbol == symbol,
                models.Trade.status == models.TradeStatus.CLOSED,
                models.Trade.close_time >= since,
            )
        )
        return result.scalars().all()

    @staticmethod
    def _session_overlap_score(hour_utc: int) -> float:
        """Score based on forex session activity."""
        # London: 08-17 UTC, NY: 13-22 UTC, Overlap: 13-17 UTC
        if 13 <= hour_utc <= 16:
            return 1.0  # London/NY overlap - best liquidity
        elif 8 <= hour_utc <= 12 or 17 <= hour_utc <= 21:
            return 0.7  # Single active session
        elif 0 <= hour_utc <= 7:
            return 0.3  # Asia / quiet
        else:
            return 0.1  # Late NY / weekend approach

    @staticmethod
    def _score_to_recommendation(score: float) -> str:
        if score >= 70:
            return "strong_buy"
        elif score >= 55:
            return "favorable"
        elif score >= 40:
            return "neutral"
        elif score >= 25:
            return "unfavorable"
        else:
            return "avoid"

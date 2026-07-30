"""PaperTradingMonitor — compute KPIs for 30-day paper trading validation.

Tracks:
- Win rate, profit factor, exit quality score
- RAG outcome coverage (% of decisions with Qdrant updates)
- XGBoost entry gate filter rate
- Emergency stop triggers
- Daily drawdown
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models
from app.enums import TradeStatus, TradeMode

logger = logging.getLogger("app.services.paper_trading_monitor")


class PaperTradingMonitor:
    """Compute paper trading KPIs and go/no-go evaluation."""

    @staticmethod
    async def compute_report(db: AsyncSession, days: int = 30) -> Dict[str, Any]:
        """Compute full paper trading report for the last N days."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Base query: paper trades in period
        result = await db.execute(
            select(models.Trade)
            .where(models.Trade.mode == TradeMode.PAPER.value)
            .where(models.Trade.close_time >= since)
        )
        trades = result.scalars().all()

        # Also include open positions for current unrealized
        open_result = await db.execute(
            select(models.Trade)
            .where(models.Trade.mode == TradeMode.PAPER.value)
            .where(models.Trade.status == TradeStatus.OPEN)
        )
        open_trades = open_result.scalars().all()

        # --- Trade metrics ---
        closed = [t for t in trades if t.status == TradeStatus.CLOSED]
        wins = [t for t in closed if (t.pnl or 0) > 0]
        losses = [t for t in closed if (t.pnl or 0) <= 0]
        total_closed = len(closed)
        win_rate = len(wins) / total_closed if total_closed > 0 else 0.0

        gross_profit = sum(t.pnl or 0 for t in wins)
        gross_loss = abs(sum(t.pnl or 0 for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        # --- Exit quality ---
        eq_scores = [t.exit_quality_score for t in closed if t.exit_quality_score is not None]
        avg_exit_quality = sum(eq_scores) / len(eq_scores) if eq_scores else 0.0

        # --- Daily returns & drawdown ---
        daily_pnl = {}
        for t in closed:
            day = t.close_time.date() if t.close_time else datetime.now(timezone.utc).date()
            daily_pnl[day] = daily_pnl.get(day, 0) + (t.pnl or 0)

        daily_returns = list(daily_pnl.values())
        max_single_day_dd = min(daily_returns) if daily_returns else 0.0

        # Cumulative equity curve
        sorted_days = sorted(daily_pnl.keys())
        cumulative = 0
        peak = 0
        max_dd_pct = 0.0
        for day in sorted_days:
            cumulative += daily_pnl[day]
            if cumulative > peak:
                peak = cumulative
            dd = (cumulative - peak) / max(peak, 1) * 100
            if dd < max_dd_pct:
                max_dd_pct = dd

        # --- RAG outcome coverage (decisions with Qdrant point ID) ---
        decisions_result = await db.execute(
            select(models.AIDecision)
            .where(models.AIDecision.timestamp >= since)
        )
        decisions = decisions_result.scalars().all()
        total_decisions = len(decisions)
        with_qdrant = sum(1 for d in decisions if d.qdrant_point_id is not None)
        rag_coverage = with_qdrant / total_decisions if total_decisions > 0 else 0.0

        # --- XGBoost gate filter rate ---
        gate_result = await db.execute(
            select(func.count(models.AIDecision.id))
            .where(models.AIDecision.timestamp >= since)
            .where(models.AIDecision.model_used == "xgb_entry_gate")
        )
        gate_blocked = gate_result.scalar() or 0
        # Total decisions excluding gate blocks
        total_non_gate = await db.execute(
            select(func.count(models.AIDecision.id))
            .where(models.AIDecision.timestamp >= since)
        )
        total_all = total_non_gate.scalar() or 1
        gate_filter_rate = gate_blocked / (total_all if total_all and total_all != 0 else 1)

        # --- Emergency stops ---
        es_result = await db.execute(
            select(func.count(models.Trade.id))
            .where(models.Trade.mode == TradeMode.PAPER.value)
            .where(models.Trade.close_time >= since)
            .where(models.Trade.close_reason == "emergency_stop")
        )
        emergency_stops = es_result.scalar() or 0

        # --- Open positions ---
        open_count = len(open_trades)
        unrealized = sum(t.unrealized_pnl or 0 for t in open_trades)

        return {
            "period_days": days,
            "report_generated_at": datetime.now(timezone.utc).isoformat(),
            "total_trades": total_closed,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 2),
            "avg_exit_quality": round(avg_exit_quality, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "net_pnl": round(gross_profit - gross_loss, 2),
            "max_single_day_drawdown": round(max_single_day_dd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "daily_returns": {str(k): round(v, 2) for k, v in daily_pnl.items()},
            "rag_outcome_coverage": round(rag_coverage, 3),
            "total_decisions": total_decisions,
            "xgb_gate_blocked": gate_blocked,
            "xgb_gate_filter_rate": round(gate_filter_rate, 3),
            "emergency_stops": emergency_stops,
            "open_positions": open_count,
            "unrealized_pnl": round(unrealized, 2),
        }

    @staticmethod
    async def evaluate_go_no_go(db: AsyncSession, days: int = 30) -> Dict[str, Any]:
        """Evaluate acceptance criteria for go/no-go gate."""
        report = await PaperTradingMonitor.compute_report(db, days=days)

        checks = {
            "win_rate_ge_52": report["win_rate"] >= 0.52,
            "profit_factor_ge_1_2": report["profit_factor"] >= 1.2,
            "max_daily_dd_le_3pct": abs(report["max_single_day_drawdown"]) <= 30,
            "exit_quality_ge_0_55": report["avg_exit_quality"] >= 0.55,
            "min_100_trades": report["total_trades"] >= 100,
            "rag_coverage_ge_90": report["rag_outcome_coverage"] >= 0.90,
            "gate_filter_15_30": 0.15 <= report["xgb_gate_filter_rate"] <= 0.30,
            "zero_emergency_stops": report["emergency_stops"] == 0,
        }

        passed = sum(checks.values())
        total = len(checks)
        go = passed >= 6  # Allow 2 failures for go/no-go

        return {
            "go": go,
            "passed": passed,
            "total_criteria": total,
            "checks": checks,
            "report": report,
        }

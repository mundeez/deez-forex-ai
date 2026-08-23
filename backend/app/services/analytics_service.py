"""Portfolio analytics from closed-trade PnL.

Round 1 metrics — computes a closed-trade equity curve and derived
statistics (max drawdown, Sharpe, expectancy) from live trade records.
"""
import logging
import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app import models

logger = logging.getLogger("app.services.analytics")


async def compute_equity_curve(
    db: AsyncSession,
    equity_balance: float = 0.0,
    reset_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Build a closed-trade equity curve ordered by close_time.

    Returns [{timestamp, equity, realized_pnl, unrealized_pnl, drawdown_pct}].
    """
    filters = [models.Trade.status == models.TradeStatus.CLOSED]
    if reset_at is not None:
        filters.append(models.Trade.close_time >= reset_at)

    result = await db.execute(
        select(models.Trade)
        .where(*filters)
        .order_by(models.Trade.close_time.asc())
    )
    trades = result.scalars().all()

    curve: List[Dict[str, Any]] = []
    cum_pnl = 0.0
    equity = equity_balance
    peak = equity

    for trade in trades:
        cum_pnl += trade.pnl or 0.0
        equity = equity_balance + cum_pnl
        if equity > peak:
            peak = equity
        drawdown_pct = ((peak - equity) / peak * 100.0) if peak > 0 else 0.0
        curve.append(
            {
                "timestamp": trade.close_time,
                "equity": round(equity, 2),
                "realized_pnl": round(cum_pnl, 2),
                "unrealized_pnl": 0.0,
                "drawdown_pct": round(drawdown_pct, 2),
            }
        )

    return curve


async def compute_portfolio_metrics(
    db: AsyncSession,
    equity_balance: float = 0.0,
    reset_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return portfolio summary plus the equity curve from closed trades."""
    filters = [models.Trade.status == models.TradeStatus.CLOSED]
    if reset_at is not None:
        filters.append(models.Trade.close_time >= reset_at)

    total_result = await db.execute(
        select(func.count(models.Trade.id)).where(*filters)
    )
    total_closed = total_result.scalar() or 0

    if total_closed == 0:
        return {
            "equity": round(equity_balance, 2),
            "daily_pnl": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": None,
            "profit_factor": None,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": None,
            "expectancy": None,
            "equity_history": [],
        }

    wins_result = await db.execute(
        select(func.count(models.Trade.id)).where(*filters, models.Trade.pnl > 0)
    )
    wins = wins_result.scalar() or 0
    losses = total_closed - wins

    gross_profit_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0.0))
        .where(*filters, models.Trade.pnl > 0)
    )
    gross_profit = gross_profit_result.scalar() or 0.0

    gross_loss_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0.0))
        .where(*filters, models.Trade.pnl <= 0)
    )
    gross_loss = abs(gross_loss_result.scalar() or 0.0)

    total_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0.0)).where(*filters)
    )
    total_pnl = total_pnl_result.scalar() or 0.0

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_start = max(start_of_day, reset_at) if reset_at is not None else start_of_day
    daily_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0.0)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.close_time >= daily_start,
        )
    )
    daily_pnl = daily_pnl_result.scalar() or 0.0

    curve = await compute_equity_curve(db, equity_balance, reset_at)
    max_drawdown_pct = max((p["drawdown_pct"] for p in curve), default=0.0)

    returns: List[float] = []
    if len(curve) >= 2:
        for i in range(1, len(curve)):
            prev_equity = curve[i - 1]["equity"]
            curr_equity = curve[i]["equity"]
            if prev_equity > 0:
                returns.append((curr_equity - prev_equity) / prev_equity)

    sharpe = None
    sortino = None
    calmar = None
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance)
        if std > 0:
            sharpe = (mean / std) * math.sqrt(260)
        downside = [r for r in returns if r < 0]
        if len(downside) >= 2:
            downside_mean = sum(downside) / len(downside)
            downside_var = sum((r - downside_mean) ** 2 for r in downside) / len(downside)
            downside_std = math.sqrt(downside_var)
            if downside_std > 0:
                sortino = (mean / downside_std) * math.sqrt(260)
        ann_return = mean * 260
        max_dd_decimal = abs(max_drawdown_pct) / 100.0 if max_drawdown_pct else 0.0
        if max_dd_decimal > 0:
            calmar = ann_return / max_dd_decimal

    expectancy = None
    if total_closed > 0:
        avg_win = gross_profit / wins if wins > 0 else 0.0
        avg_loss = gross_loss / losses if losses > 0 else 0.0
        win_rate = wins / total_closed
        expectancy = (avg_win * win_rate) - (avg_loss * (1 - win_rate))

    return {
        "equity": round(equity_balance + total_pnl, 2),
        "daily_pnl": round(daily_pnl, 2),
        "realized_pnl": round(total_pnl, 2),
        "unrealized_pnl": 0.0,
        "total_trades": total_closed,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": round(wins / total_closed * 100, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        "max_drawdown_pct": round(abs(max_drawdown_pct), 2),
        "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
        "sortino_ratio": round(sortino, 2) if sortino is not None else None,
        "calmar_ratio": round(calmar, 2) if calmar is not None else None,
        "expectancy": round(expectancy, 2) if expectancy is not None else None,
        "equity_history": curve,
    }


def _apply_reset_filter(reset_at: Optional[datetime]):
    """Return base filters for closed-trade analytics."""
    filters = [models.Trade.status == models.TradeStatus.CLOSED]
    if reset_at is not None:
        filters.append(models.Trade.close_time >= reset_at)
    return filters


async def compute_analytics_by_session(
    db: AsyncSession,
    reset_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Aggregate closed-trade stats by session_at_close."""
    filters = _apply_reset_filter(reset_at)
    result = await db.execute(
        select(
            models.Trade.session_at_close,
            func.count(models.Trade.id).label("total"),
            func.sum(case((models.Trade.pnl > 0, 1), else_=0)).label("wins"),
            func.coalesce(func.sum(models.Trade.pnl), 0.0).label("total_pnl"),
            func.coalesce(func.sum(case((models.Trade.pnl > 0, models.Trade.pnl), else_=0)), 0.0).label("gross_profit"),
            func.coalesce(func.sum(func.abs(case((models.Trade.pnl <= 0, models.Trade.pnl), else_=0))), 0.0).label("gross_loss"),
        )
        .where(*filters)
        .group_by(models.Trade.session_at_close)
        .order_by(models.Trade.session_at_close)
    )
    rows = result.all()
    out = []
    for r in rows:
        session = r.session_at_close or "unknown"
        total = r.total or 0
        wins = r.wins or 0
        losses = total - wins
        total_pnl = r.total_pnl or 0.0
        avg_pnl = total_pnl / total if total else 0.0
        pf = r.gross_profit / r.gross_loss if r.gross_loss else None
        out.append({
            "session": session,
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(wins / total * 100, 2) if total else None,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "profit_factor": round(pf, 2) if pf is not None else None,
        })
    return out


async def compute_analytics_by_hour(
    db: AsyncSession,
    reset_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Aggregate closed-trade stats by hour-of-day."""
    filters = _apply_reset_filter(reset_at)
    result = await db.execute(
        select(
            func.extract("hour", models.Trade.close_time).label("hour"),
            models.Trade.symbol,
            func.count(models.Trade.id).label("total"),
            func.sum(case((models.Trade.pnl > 0, 1), else_=0)).label("wins"),
            func.coalesce(func.sum(models.Trade.pnl), 0.0).label("total_pnl"),
        )
        .where(*filters)
        .group_by(func.extract("hour", models.Trade.close_time), models.Trade.symbol)
        .order_by(func.extract("hour", models.Trade.close_time), models.Trade.symbol)
    )
    rows = result.all()
    hour_map: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        hour = int(r.hour)
        if hour not in hour_map:
            hour_map[hour] = {
                "hour": hour,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0.0,
                "symbols": set(),
            }
        hour_map[hour]["total_trades"] += r.total or 0
        hour_map[hour]["winning_trades"] += r.wins or 0
        hour_map[hour]["total_pnl"] += r.total_pnl or 0.0
        hour_map[hour]["symbols"].add(r.symbol)

    out = []
    for hour in sorted(hour_map.keys()):
        data = hour_map[hour]
        total = data["total_trades"]
        wins = data["winning_trades"]
        losses = total - wins
        out.append({
            "hour": hour,
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(wins / total * 100, 2) if total else None,
            "total_pnl": round(data["total_pnl"], 2),
            "avg_pnl": round(data["total_pnl"] / total, 2) if total else 0.0,
            "symbols": sorted(list(data["symbols"])),
        })
    return out


async def compute_holding_distribution(
    db: AsyncSession,
    reset_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Bucket closed trades by holding duration."""
    filters = _apply_reset_filter(reset_at)
    result = await db.execute(
        select(models.Trade)
        .where(*filters)
        .order_by(models.Trade.close_time.asc())
    )
    trades = result.scalars().all()

    buckets = [
        ("0-5m", 0, 5),
        ("5-30m", 5, 30),
        ("30m-2h", 30, 120),
        ("2-8h", 120, 480),
        ("8-24h", 480, 1440),
        (">1d", 1440, None),
    ]
    bucket_rows = {name: {"bucket": name, "min_minutes": lo, "max_minutes": hi, "trades": []} for name, lo, hi in buckets}

    for t in trades:
        mins = t.actual_holding_min
        if mins is None:
            continue
        for name, lo, hi in buckets:
            if mins >= lo and (hi is None or mins < hi):
                bucket_rows[name]["trades"].append(t)
                break

    out = []
    for name, lo, hi in buckets:
        data = bucket_rows[name]
        tr = data["trades"]
        total = len(tr)
        wins = sum(1 for x in tr if (x.pnl or 0) > 0)
        losses = total - wins
        total_pnl = sum(x.pnl or 0.0 for x in tr)
        out.append({
            "bucket": name,
            "min_minutes": lo,
            "max_minutes": hi,
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(wins / total * 100, 2) if total else None,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total else 0.0,
        })
    return out

"""Portfolio analytics from closed-trade PnL.

Round 1 metrics — computes a closed-trade equity curve and derived
statistics (max drawdown, Sharpe, expectancy) from live trade records.
"""
import logging
import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

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

    sharpe = None
    if len(curve) >= 2:
        returns = []
        for i in range(1, len(curve)):
            prev_equity = curve[i - 1]["equity"]
            curr_equity = curve[i]["equity"]
            if prev_equity > 0:
                returns.append((curr_equity - prev_equity) / prev_equity)
        if len(returns) >= 2:
            mean = sum(returns) / len(returns)
            variance = sum((r - mean) ** 2 for r in returns) / len(returns)
            std = math.sqrt(variance)
            if std > 0:
                sharpe = (mean / std) * math.sqrt(260)

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
        "expectancy": round(expectancy, 2) if expectancy is not None else None,
        "equity_history": curve,
    }

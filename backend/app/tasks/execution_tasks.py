import asyncio
from datetime import datetime, timedelta
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.services.execution.executor import ExecutionService
from sqlalchemy import select, func
from app import models


@celery_app.task
def check_open_positions():
    async def _check():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_trade_event
            executor = ExecutionService()
            closed_trades = await executor.check_and_close_positions(db)
            for trade in closed_trades:
                await broadcast_trade_event("closed", {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "direction": trade.direction,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "mode": trade.mode,
                })
        return {"checked": True}
    return asyncio.run(_check())


@celery_app.task
def update_daily_pnl():
    async def _update():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_settings_change
            today = datetime.utcnow().date()
            start_of_day = datetime.combine(today, datetime.min.time())

            result = await db.execute(
                select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
                    models.Trade.status == models.TradeStatus.CLOSED,
                    models.Trade.close_time >= start_of_day,
                )
            )
            realized = result.scalar() or 0.0

            result = await db.execute(
                select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
                    models.Trade.status == models.TradeStatus.OPEN,
                )
            )
            unrealized = result.scalar() or 0.0

            equity = 10000.0 + realized + unrealized

            db_pnl = models.DailyPnl(
                date=datetime.utcnow(),
                symbol="PORTFOLIO",
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                equity=equity,
            )
            db.add(db_pnl)

            # Also create account snapshot for equity curve
            result = await db.execute(select(func.count(models.Trade.id)).where(models.Trade.status == models.TradeStatus.OPEN))
            open_count = result.scalar() or 0

            snapshot = models.AccountSnapshot(
                equity=equity,
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                total_trades=0,
                open_trades=open_count,
            )
            db.add(snapshot)

            await db.commit()

            await broadcast_settings_change({
                "type": "portfolio_update",
                "equity": equity,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "open_trades": open_count,
            })

        return {"realized": realized, "unrealized": unrealized}
    return asyncio.run(_update())

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
            executor = ExecutionService()
            await executor.check_and_close_positions(db)
        return {"checked": True}
    return asyncio.run(_check())


@celery_app.task
def update_daily_pnl():
    async def _update():
        async with AsyncSessionLocal() as db:
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

            db_pnl = models.DailyPnl(
                date=datetime.utcnow(),
                symbol="EURUSD",
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                equity=10000.0 + realized + unrealized,
            )
            db.add(db_pnl)
            await db.commit()
        return {"realized": realized, "unrealized": unrealized}
    return asyncio.run(_update())

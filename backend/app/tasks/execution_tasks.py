import asyncio
from datetime import datetime, timedelta, time
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.services.execution.executor import ExecutionService
from app.services.settings_service import get_setting_bool, get_setting_float
from sqlalchemy import select, func
from app import models


@celery_app.task
def check_open_positions():
    async def _check():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_trade_event
            executor = ExecutionService()
            # Check SL/TP first
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
                    "close_reason": "sl_tp",
                })
            # Then check time-based closes
            time_closed = await executor.check_and_close_time_based_positions(db)
            for trade in time_closed:
                await broadcast_trade_event("closed", {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "direction": trade.direction,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "mode": trade.mode,
                    "close_reason": "max_duration",
                })
        return {"checked": True, "sl_tp_closed": len(closed_trades), "time_closed": len(time_closed)}
    return asyncio.run(_check())


@celery_app.task
def close_eod_positions():
    async def _close():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_trade_event
            eod_enabled = await get_setting_bool(db, "eod_close_enabled")
            if not eod_enabled:
                return {"closed": 0, "reason": "EOD close disabled"}

            executor = ExecutionService()
            closed_trades = await executor.close_all_open_positions(db, close_reason="eod")
            for trade in closed_trades:
                await broadcast_trade_event("closed", {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "direction": trade.direction,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "mode": trade.mode,
                    "close_reason": "eod",
                })
            return {"closed": len(closed_trades), "reason": "eod"}
    return asyncio.run(_close())


@celery_app.task
def close_weekend_positions():
    async def _close():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_trade_event
            weekend_enabled = await get_setting_bool(db, "weekend_close_enabled")
            if not weekend_enabled:
                return {"closed": 0, "reason": "Weekend close disabled"}

            executor = ExecutionService()
            closed_trades = await executor.close_all_open_positions(db, close_reason="weekend")
            for trade in closed_trades:
                await broadcast_trade_event("closed", {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "direction": trade.direction,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "mode": trade.mode,
                    "close_reason": "weekend",
                })
            return {"closed": len(closed_trades), "reason": "weekend"}
    return asyncio.run(_close())


@celery_app.task
def update_daily_pnl():
    async def _update():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_settings_change
            today = datetime.utcnow().date()
            start_of_day = datetime.combine(today, datetime.min.time())
            equity_balance = await get_setting_float(db, "equity_balance")

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

            equity = equity_balance + realized + unrealized

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

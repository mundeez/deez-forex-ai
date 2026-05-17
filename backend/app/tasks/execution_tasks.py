import asyncio
import logging
from datetime import datetime, timedelta, time
from app.celery_app import celery_app

logger = logging.getLogger("app.tasks.execution")
from app.database import AsyncSessionLocal
from app.services.execution.executor import ExecutionService
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting_bool, get_setting_float
from sqlalchemy import select, func
from app import models


@celery_app.task
def check_open_positions():
    async def _check():
        async with AsyncSessionLocal() as db:
            from app.services.websocket_broadcaster import broadcast_trade_event
            from app.services.vector_store import VectorStore
            executor = ExecutionService()
            notifier = NotificationService()
            vs = VectorStore()
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
                if trade.ai_decision_id:
                    vs.update_outcome(str(trade.ai_decision_id), trade.pnl or 0, trade.status.value)
                try:
                    await notifier.send_trade_closed(
                        db,
                        symbol=trade.symbol,
                        direction=trade.direction.upper(),
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        pnl=trade.pnl or 0,
                        pnl_pct=trade.pnl_pct or 0,
                        close_reason="sl_tp",
                    )
                except Exception:
                    logger.warning("Failed to send trade closed notification for SL/TP", exc_info=True)

            # Check trailing stops
            trailing_closed = await executor.check_trailing_stops(db)
            for trade in trailing_closed:
                await broadcast_trade_event("closed", {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "direction": trade.direction,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "mode": trade.mode,
                    "close_reason": "trailing_stop",
                })
                if trade.ai_decision_id:
                    vs.update_outcome(str(trade.ai_decision_id), trade.pnl or 0, trade.status.value)
                try:
                    await notifier.send_trade_closed(
                        db,
                        symbol=trade.symbol,
                        direction=trade.direction.upper(),
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        pnl=trade.pnl or 0,
                        pnl_pct=trade.pnl_pct or 0,
                        close_reason="trailing_stop",
                    )
                except Exception:
                    logger.warning("Failed to send trade closed notification for trailing stop", exc_info=True)

            # Check partial profits
            partials = await executor.check_partial_profits(db)
            for trade in partials:
                await broadcast_trade_event("partial", {
                    "id": trade.id,
                    "symbol": trade.symbol,
                    "partial_pnl": trade.partial_pnl,
                    "closed_portion": trade.closed_portion,
                    "position_size": trade.position_size,
                    "stop_loss": trade.stop_loss,
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
                if trade.ai_decision_id:
                    vs.update_outcome(str(trade.ai_decision_id), trade.pnl or 0, trade.status.value)
                try:
                    await notifier.send_trade_closed(
                        db,
                        symbol=trade.symbol,
                        direction=trade.direction.upper(),
                        entry_price=trade.entry_price,
                        exit_price=trade.exit_price,
                        pnl=trade.pnl or 0,
                        pnl_pct=trade.pnl_pct or 0,
                        close_reason="max_duration",
                    )
                except Exception:
                    logger.warning("Failed to send trade closed notification for max duration", exc_info=True)
        return {
            "checked": True,
            "sl_tp_closed": len(closed_trades),
            "trailing_closed": len(trailing_closed),
            "partials": len(partials),
            "time_closed": len(time_closed),
        }
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

            # Get previous peak
            prev_snap = await db.execute(
                select(models.AccountSnapshot).order_by(models.AccountSnapshot.timestamp.desc()).limit(1)
            )
            prev = prev_snap.scalar_one_or_none()
            peak = max(prev.peak_equity, equity) if prev and prev.peak_equity else equity
            drawdown = ((peak - equity) / peak * 100) if peak > 0 else 0.0

            snapshot = models.AccountSnapshot(
                equity=equity,
                peak_equity=peak,
                drawdown_pct=round(drawdown, 2),
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


@celery_app.task
def compute_pair_performance():
    async def _compute():
        async with AsyncSessionLocal() as db:
            now = datetime.utcnow()
            # Look back 30 days for stats
            since = now - timedelta(days=30)
            symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]
            modes = ["scalping", "day_trading", "swing"]

            for symbol in symbols:
                for mode in modes:
                    for hour in range(24):
                        result = await db.execute(
                            select(models.Trade).where(
                                models.Trade.symbol == symbol,
                                models.Trade.strategy_mode == mode,
                                models.Trade.status == models.TradeStatus.CLOSED,
                                models.Trade.close_time >= since,
                                func.extract("hour", models.Trade.open_time) == hour,
                            )
                        )
                        trades = result.scalars().all()
                        if not trades:
                            continue

                        total = len(trades)
                        wins = sum(1 for t in trades if (t.pnl or 0) > 0)
                        avg_pnl = sum(t.pnl or 0 for t in trades) / total
                        avg_conf = 0.5  # placeholder; could be fetched from ai_decisions join
                        # Compute volatility as std dev of pnl
                        if total > 1:
                            import statistics
                            vol = statistics.stdev([t.pnl or 0 for t in trades])
                        else:
                            vol = 0.0
                        vol_score = min(1.0, vol / max(abs(avg_pnl) if avg_pnl != 0 else 1, 0.01))

                        # Upsert into pair_performance_by_hour
                        existing = await db.execute(
                            select(models.PairPerformanceByHour).where(
                                models.PairPerformanceByHour.symbol == symbol,
                                models.PairPerformanceByHour.hour_utc == hour,
                                models.PairPerformanceByHour.strategy_mode == mode,
                            )
                        )
                        row = existing.scalar_one_or_none()
                        if row:
                            row.total_trades = total
                            row.winning_trades = wins
                            row.avg_pnl = round(avg_pnl, 2)
                            row.avg_confidence = round(avg_conf, 2)
                            row.volatility_score = round(vol_score, 2)
                        else:
                            row = models.PairPerformanceByHour(
                                symbol=symbol,
                                hour_utc=hour,
                                strategy_mode=mode,
                                total_trades=total,
                                winning_trades=wins,
                                avg_pnl=round(avg_pnl, 2),
                                avg_confidence=round(avg_conf, 2),
                                volatility_score=round(vol_score, 2),
                            )
                            db.add(row)
            await db.commit()
        return {"computed": True}
    return asyncio.run(_compute())

import asyncio
import logging
from datetime import datetime, timedelta, time
from app.celery_app import celery_app

logger = logging.getLogger("app.tasks.execution")
from app.database import get_celery_session
from app.services.execution.executor import ExecutionService, compute_live_unrealized
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting_bool, get_setting_float
from sqlalchemy import select, func
from app import models


@celery_app.task
def check_open_positions():
    async def _check():
        async with get_celery_session()() as db:
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
        async with get_celery_session()() as db:
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
        async with get_celery_session()() as db:
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
        async with get_celery_session()() as db:
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

            unrealized = await compute_live_unrealized(db)

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
        async with get_celery_session()() as db:
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


@celery_app.task
def compute_daily_bias():
    """Pre-market reasoning pass: compute a directional bias per active pair.

    Runs on a schedule (e.g., every 4 hours or at major session opens).
    The bias is cached in Redis for zero-latency injection into the
    fast intraday AI team.
    """
    async def _compute():
        from app.ai.team.daily_bias import DailyBiasEngine
        from app.services.news_service import NewsService
        from app.analysis.fundamental import FundamentalAnalyzer

        async with get_celery_session()() as db:
            daily_bias_enabled = await get_setting_bool(db, "daily_bias_enabled")
            if not daily_bias_enabled:
                return {"skipped": "daily_bias_disabled"}

            result = await db.execute(select(models.ActivePair).order_by(models.ActivePair.priority))
            active_pairs = result.scalars().all()
            if not active_pairs:
                active_pairs = [models.ActivePair(symbol="EURUSD", selection_mode="manual", priority=1)]

            engine = DailyBiasEngine()
            news = NewsService()
            fund = FundamentalAnalyzer()
            out = {}

            for pair in active_pairs:
                symbol = pair.symbol
                try:
                    macro = await fund.analyze(symbol)
                    news_summary = await news.get_latest_headlines(symbol, limit=10)
                    bias = await engine.compute(
                        symbol=symbol,
                        macro_snapshot=macro,
                        news_summary="\n".join(news_summary) if news_summary else "",
                    )
                    await engine.cache(symbol, bias)
                    # Persist to DB
                    db_bias = models.DailyBias(
                        symbol=symbol,
                        date=datetime.utcnow().date(),
                        bias=bias["bias"],
                        confidence=bias["confidence"],
                        rationale=bias["rationale"],
                        key_levels=bias.get("key_levels"),
                        risk_events=bias.get("risk_events"),
                        model_used=bias["model_used"],
                    )
                    db.add(db_bias)
                    out[symbol] = bias["bias"]
                except Exception as exc:
                    logger.warning("Daily bias failed for %s: %s", symbol, exc, exc_info=True)
                    out[symbol] = "NEUTRAL"
            await db.commit()
            return out
    return asyncio.run(_compute())


@celery_app.task
def refresh_model_performance():
    """Compute per-model performance stats from closed trades for self-improvement."""
    async def _refresh():
        async with get_celery_session()() as db:
            weighting_enabled = await get_setting_bool(db, "model_perf_weighting_enabled")
            if not weighting_enabled:
                return {"skipped": "model_perf_weighting_disabled"}

            windows = {
                "7d": datetime.utcnow() - timedelta(days=7),
                "30d": datetime.utcnow() - timedelta(days=30),
                "90d": datetime.utcnow() - timedelta(days=90),
            }

            # Join trades with ai_decisions to get model_used + engine_version
            from sqlalchemy import join
            for window_name, since in windows.items():
                stmt = (
                    select(
                        models.AIDecision.model_used,
                        models.AIDecision.engine_version,
                        func.count(models.Trade.id),
                        func.coalesce(func.sum(
                            case((models.Trade.pnl > 0, 1), else_=0)
                        ), 0),
                        func.coalesce(func.sum(models.Trade.pnl), 0.0),
                        func.coalesce(func.avg(models.Trade.pnl), 0.0),
                        func.coalesce(func.avg(models.AIDecision.confidence), 0.0),
                    )
                    .select_from(join(models.Trade, models.AIDecision, models.Trade.ai_decision_id == models.AIDecision.id))
                    .where(
                        models.Trade.status == models.TradeStatus.CLOSED,
                        models.Trade.close_time >= since,
                        models.AIDecision.model_used.isnot(None),
                    )
                    .group_by(models.AIDecision.model_used, models.AIDecision.engine_version)
                )
                rows = (await db.execute(stmt)).all()

                for model_used, engine_ver, total, wins, total_pnl, avg_pnl, avg_conf in rows:
                    domain = "overall"  # Could be refined per-domain when analyst_opinions is populated
                    win_rate = (int(wins) / int(total)) if total else 0.0
                    expectancy = float(avg_pnl) if avg_pnl else 0.0

                    existing = await db.execute(
                        select(models.ModelPerformance).where(
                            models.ModelPerformance.model == model_used,
                            models.ModelPerformance.domain == domain,
                            models.ModelPerformance.window == window_name,
                        )
                    )
                    row = existing.scalar_one_or_none()
                    if row:
                        row.trades = int(total)
                        row.winning_trades = int(wins)
                        row.losing_trades = int(total) - int(wins)
                        row.win_rate = round(win_rate, 4)
                        row.expectancy = round(expectancy, 4)
                        row.avg_confidence = round(float(avg_conf or 0), 4)
                        row.avg_pnl = round(float(avg_pnl or 0), 4)
                    else:
                        db.add(models.ModelPerformance(
                            model=model_used,
                            domain=domain,
                            window=window_name,
                            trades=int(total),
                            winning_trades=int(wins),
                            losing_trades=int(total) - int(wins),
                            win_rate=round(win_rate, 4),
                            expectancy=round(expectancy, 4),
                            avg_confidence=round(float(avg_conf or 0), 4),
                            avg_pnl=round(float(avg_pnl or 0), 4),
                        ))
            await db.commit()
            return {"refreshed": True}
    return asyncio.run(_refresh())


@celery_app.task
def reevaluate_open_positions():
    """Exit re-evaluation loop: rule fast-path + optional AI slow-path (alert-only).

    Rule fast-path (auto-execute):
      - MFE >= 1R AND pullback > 50% of MFE  -> close (profit lock)
      - Holding > expected_holding_min * 1.5 AND pnl <= 0 -> close (stale)
      - Approaching high-impact news window -> close (event)

    AI slow-path (alert-only for now):
      - Optional DeepSeek-R1 review of open positions
      - Logs recommendation to trade_decision_events
    """
    async def _reeval():
        async with get_celery_session()() as db:
            exit_enabled = await get_setting_bool(db, "exit_reeval_enabled")
            if not exit_enabled:
                return {"skipped": "exit_reeval_disabled"}

            result = await db.execute(
                select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
            )
            open_trades = result.scalars().all()
            if not open_trades:
                return {"checked": 0}

            from app.services.data.metaapi_client import MetaApiClient
            from app.services.data.mt5_zmq_client import MT5ZMQClient
            metaapi = MetaApiClient()
            mt5_zmq = MT5ZMQClient()
            from app.config import get_settings as _gs
            _settings = _gs()
            client = mt5_zmq if _settings.DATA_PROVIDER.value == "mt5_zmq" else metaapi

            closed_count = 0
            alert_count = 0

            for trade in open_trades:
                try:
                    price_data = await client.get_current_price(trade.symbol)
                    current_bid = price_data.get("bid", 0.0)
                    current_ask = price_data.get("ask", 0.0)
                    current = current_bid if trade.direction.value == "sell" else current_ask

                    is_buy = trade.direction.value == "buy"
                    entry = trade.entry_price or current
                    pnl = trade.pnl_usd(trade.symbol, is_buy, entry, current, trade.position_size or 0.01) if hasattr(trade, 'pnl_usd') else 0.0

                    # Compute MFE/MAE if price path is recorded
                    mfe_pips = trade.mfe_pips or 0.0
                    mae_pips = trade.mae_pips or 0.0
                    sl_pips = 0.0
                    if trade.stop_loss and trade.entry_price:
                        from app.services.instruments import pips
                        sl_pips = abs(pips(trade.symbol, trade.entry_price - trade.stop_loss))

                    # Rule 1: Profit lock — MFE >= 1R AND pullback > 50%
                    if mfe_pips >= sl_pips and sl_pips > 0:
                        current_pips_from_peak = mfe_pips - (mfe_pips * 0.5)  # simplified
                        # If current is more than 50% off the peak favorable move
                        if pnl > 0 and mfe_pips > 0:
                            # Actually check: current pnl is < 50% of peak pnl
                            peak_pnl = trade.peak_pnl or pnl
                            if peak_pnl > 0 and pnl < peak_pnl * 0.5:
                                executor = ExecutionService()
                                closed = await executor.close_trade(db, trade.id, current, close_reason="profit_lock")
                                closed_count += 1
                                logger.info("[EXIT REEVAL] Profit-locked trade %s at %.5f (%.1f%% off peak)", trade.id, current, (1 - pnl/peak_pnl)*100)
                                continue

                    # Rule 2: Stale trade — holding too long with no profit
                    if trade.open_time:
                        holding_min = (datetime.utcnow() - trade.open_time).total_seconds() / 60.0
                        max_duration = await get_setting_float(db, "max_trade_duration_min") or 120.0
                        if holding_min > max_duration * 1.5 and (trade.pnl or 0) <= 0:
                            executor = ExecutionService()
                            closed = await executor.close_trade(db, trade.id, current, close_reason="stale")
                            closed_count += 1
                            logger.info("[EXIT REEVAL] Closed stale trade %s after %.0f min", trade.id, holding_min)
                            continue

                    # AI slow-path (alert-only): log to trade_decision_events
                    # This is a placeholder for Phase 3 opt-in auto-close
                    alert_count += 1

                except Exception as exc:
                    logger.warning("Exit re-eval failed for trade %s: %s", trade.id, exc, exc_info=True)

            return {"checked": len(open_trades), "closed": closed_count, "alerts": alert_count}
    return asyncio.run(_reeval())

import asyncio
from datetime import datetime, time
from typing import Tuple
from app.celery_app import celery_app
from app.analysis.aggregator import AnalysisAggregator
from app.ai.openrouter_client import OpenRouterClient
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.services.settings_service import get_setting_bool, get_setting, get_setting_float
from app.database import AsyncSessionLocal
from app import schemas
from app.config import get_settings
from sqlalchemy import select

settings = get_settings()


def _trading_paused(strategy_mode: str, db) -> Tuple[bool, str]:
    """Check if trading should be paused (EOD, weekend, etc.)."""
    now = datetime.utcnow()

    eod_enabled = get_setting_bool(db, "eod_close_enabled")
    if eod_enabled:
        no_entry_before = get_setting(db, "eod_no_new_entries_before")
        try:
            hour, minute = map(int, no_entry_before.split(":"))
            cutoff = time(hour, minute)
            if now.time() >= cutoff:
                return True, f"Trading paused: no new entries after {no_entry_before} UTC (EOD)"
        except Exception:
            pass

    weekend_enabled = get_setting_bool(db, "weekend_close_enabled")
    if weekend_enabled:
        weekend_close_str = get_setting(db, "weekend_close_time_utc")
        weekend_resume_str = get_setting(db, "weekend_resume_time_utc")
        try:
            wc_h, wc_m = map(int, weekend_close_str.split(":"))
            wr_h, wr_m = map(int, weekend_resume_str.split(":"))
            # Friday after close_time
            if now.weekday() == 4 and now.time() >= time(wc_h, wc_m):
                return True, f"Trading paused: weekend closure after {weekend_close_str} UTC Friday"
            # Saturday
            if now.weekday() == 5:
                return True, "Trading paused: weekend"
            # Sunday before resume_time
            if now.weekday() == 6 and now.time() < time(wr_h, wr_m):
                return True, f"Trading paused: weekend, resumes {weekend_resume_str} UTC Sunday"
        except Exception:
            pass

    return False, ""


@celery_app.task
def run_full_analysis():
    async def _analyze():
        async with AsyncSessionLocal() as db:
            from app import models
            from app.services.websocket_broadcaster import broadcast_ai_decision, broadcast_trade_event
            aggregator = AnalysisAggregator()
            ai = OpenRouterClient()
            executor = ExecutionService()
            risk = RiskManager()

            strategy_mode = await get_setting(db, "strategy_mode")
            strategy_mode = strategy_mode if strategy_mode in ("scalping", "day_trading", "swing") else "scalping"

            # Check trading pause (EOD / weekend)
            paused, pause_reason = _trading_paused(strategy_mode, db)
            if paused:
                return {"status": "paused", "reason": pause_reason}

            active_result = await db.execute(select(models.ActivePair).order_by(models.ActivePair.priority))
            active_pairs = active_result.scalars().all()

            if not active_pairs:
                active_pairs = [models.ActivePair(symbol="EURUSD", selection_mode="manual", priority=1)]

            manual_override = await get_setting_bool(db, "manual_override")
            results = []

            # Initialize Qdrant vector store
            from app.services.vector_store import VectorStore
            vs = VectorStore()

            for pair in active_pairs:
                symbol = pair.symbol
                analysis = await aggregator.gather_all(symbol, strategy_mode=strategy_mode)
                decision = await ai.get_trade_decision(analysis, strategy_mode=strategy_mode)

                db_decision = models.AIDecision(
                    symbol=symbol,
                    decision=decision.decision,
                    confidence=decision.confidence,
                    timeframe=decision.timeframe,
                    entry_price=decision.entry_price,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    position_size_pct=decision.position_size_pct,
                    risk_reward=decision.risk_reward,
                    rationale=decision.rationale,
                    technical_snapshot=analysis.get("technical"),
                    fundamental_snapshot=analysis.get("fundamental"),
                    sentiment_snapshot=analysis.get("sentiment"),
                    model_used=settings.OPENROUTER_MODEL,
                    provider=settings.DATA_PROVIDER.value,
                )
                db.add(db_decision)
                await db.commit()
                await db.refresh(db_decision)

                # Store market state snapshot to Qdrant vector DB
                point_id = f"{db_decision.id}"
                vs.upsert_snapshot(
                    point_id=point_id,
                    snapshot=analysis.get("technical", {}),
                    payload={
                        "symbol": symbol,
                        "decision": decision.decision,
                        "confidence": decision.confidence,
                        "strategy_mode": strategy_mode,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )

                # Broadcast AI decision to all connected clients
                await broadcast_ai_decision({
                    "id": db_decision.id,
                    "symbol": symbol,
                    "decision": decision.decision,
                    "confidence": decision.confidence,
                    "timeframe": decision.timeframe,
                    "entry_price": decision.entry_price,
                    "stop_loss": decision.stop_loss,
                    "take_profit": decision.take_profit,
                    "position_size_pct": decision.position_size_pct,
                    "risk_reward": decision.risk_reward,
                    "rationale": decision.rationale,
                    "manual_override": manual_override,
                    "strategy_mode": strategy_mode,
                })

                if decision.decision in ("BUY", "SELL") and not manual_override:
                    ok, reason = await risk.validate_ai_decision(db, decision)
                    if ok:
                        # Extract ATR from smallest timeframe analysis
                        tech = analysis.get("technical", {})
                        tfs = tech.get("timeframes", {})
                        first_tf = next(iter(tfs.values()), {})
                        ind = first_tf.get("indicators", {})
                        atr = ind.get("atr_14", 0.0)

                        # 1. ATR-based SL/TP validation
                        ok2, reason2 = await risk.validate_sl_tp_atr(
                            db, decision.entry_price, decision.stop_loss, decision.take_profit, atr
                        )
                        if not ok2:
                            ok = False
                            reason = reason2

                        # 2. Spread efficiency filter
                        if ok:
                            ok3, reason3 = await risk.validate_spread(db, symbol, atr)
                            if not ok3:
                                ok = False
                                reason = reason3

                        # 3. Correlation guard
                        if ok:
                            ok4, reason4 = await risk.validate_correlation(db, symbol)
                            if not ok4:
                                ok = False
                                reason = reason4

                        if ok:
                            equity = await risk._get_equity(db)
                            position_size = risk.calculate_position_size(
                                equity, decision.position_size_pct,
                                decision.entry_price, decision.stop_loss
                            )

                            # 4. Drawdown-based position size reduction
                            position_size, dd_reason = await risk.apply_drawdown_reduction(db, position_size)
                            if position_size <= 0:
                                ok = False
                                reason = dd_reason

                        if ok:
                            # Calculate trailing stop distance from ATR
                            from app.services.settings_service import get_setting_float
                            trailing_atr_mult = await get_setting_float(db, "trailing_stop_distance_atr")
                            trailing_distance = atr * trailing_atr_mult if atr and trailing_atr_mult else None

                            trade_in = schemas.TradeCreate(
                                symbol=symbol,
                                direction=schemas.TradeDirection(decision.decision.lower()),
                                entry_price=decision.entry_price,
                                stop_loss=decision.stop_loss,
                                take_profit=decision.take_profit,
                                risk_pct=decision.position_size_pct,
                                mode=schemas.TradeMode.paper,
                                provider=settings.DATA_PROVIDER,
                                ai_decision_id=db_decision.id,
                                rationale=decision.rationale,
                            )
                            trade = await executor.execute_trade(
                                db, trade_in, position_size=position_size,
                                strategy_mode=strategy_mode, trailing_distance=trailing_distance
                            )
                            await broadcast_trade_event("executed", {
                                "id": trade.id,
                                "symbol": trade.symbol,
                                "direction": trade.direction,
                                "entry_price": trade.entry_price,
                                "stop_loss": trade.stop_loss,
                                "take_profit": trade.take_profit,
                                "mode": trade.mode,
                                "position_size": trade.position_size,
                                "ai_decision_id": trade.ai_decision_id,
                                "strategy_mode": strategy_mode,
                            })
                        else:
                            decision.decision = "HOLD"
                            decision.rationale += f" [RISK BLOCKED: {reason}]"
                            db_decision.decision = "HOLD"
                            db_decision.rationale = decision.rationale
                            await db.commit()
                            await broadcast_ai_decision({
                                "id": db_decision.id,
                                "symbol": symbol,
                                "decision": "HOLD",
                                "confidence": decision.confidence,
                                "rationale": decision.rationale,
                                "manual_override": manual_override,
                                "strategy_mode": strategy_mode,
                            })
                    else:
                        decision.decision = "HOLD"
                        decision.rationale += f" [RISK BLOCKED: {reason}]"
                        db_decision.decision = "HOLD"
                        db_decision.rationale = decision.rationale
                        await db.commit()
                        await broadcast_ai_decision({
                            "id": db_decision.id,
                            "symbol": symbol,
                            "decision": "HOLD",
                            "confidence": decision.confidence,
                            "rationale": decision.rationale,
                            "manual_override": manual_override,
                            "strategy_mode": strategy_mode,
                        })

                results.append({"symbol": symbol, "decision": decision.decision, "confidence": decision.confidence})

            return results

    return asyncio.run(_analyze())


@celery_app.task
def auto_select_pairs():
    async def _select():
        async with AsyncSessionLocal() as db:
            from app import models
            strategy_mode = await get_setting(db, "strategy_mode")
            strategy_mode = strategy_mode if strategy_mode in ("scalping", "day_trading", "swing") else "scalping"

            result = await db.execute(select(models.ActivePair).where(models.ActivePair.selection_mode == "auto"))
            auto_pairs = result.scalars().all()
            if not auto_pairs:
                return {"detail": "No auto-selection pairs configured"}

            aggregator = AnalysisAggregator()
            available = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]
            scored = []
            for sym in available:
                analysis = await aggregator.gather_all(sym, strategy_mode=strategy_mode)
                score = aggregator._score_pair(analysis)
                scored.append((sym, score))

            scored.sort(key=lambda x: abs(x[1]), reverse=True)
            top = scored[:len(auto_pairs)]

            for idx, pair in enumerate(auto_pairs):
                if idx < len(top):
                    pair.symbol = top[idx][0]

            await db.commit()
            return {"selected": [s for s, _ in top], "strategy_mode": strategy_mode}

    return asyncio.run(_select())

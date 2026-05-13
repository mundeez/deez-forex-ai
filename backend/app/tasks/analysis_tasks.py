import asyncio
from app.celery_app import celery_app
from app.analysis.aggregator import AnalysisAggregator
from app.ai.openrouter_client import OpenRouterClient
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.services.settings_service import get_setting_bool
from app.database import AsyncSessionLocal
from app import schemas
from sqlalchemy import select


@celery_app.task
def run_full_analysis():
    async def _analyze():
        async with AsyncSessionLocal() as db:
            from app import models
            aggregator = AnalysisAggregator()
            ai = OpenRouterClient()
            executor = ExecutionService()
            risk = RiskManager()

            active_result = await db.execute(select(models.ActivePair).order_by(models.ActivePair.priority))
            active_pairs = active_result.scalars().all()

            if not active_pairs:
                active_pairs = [models.ActivePair(symbol="EURUSD", selection_mode="manual", priority=1)]

            manual_override = await get_setting_bool(db, "manual_override")
            results = []

            for pair in active_pairs:
                symbol = pair.symbol
                analysis = await aggregator.gather_all(symbol)
                decision = await ai.get_trade_decision(analysis)

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
                    model_used="anthropic/claude-sonnet-4.5",
                )
                db.add(db_decision)
                await db.commit()

                if decision.decision in ("BUY", "SELL") and not manual_override:
                    ok, reason = await risk.validate_ai_decision(db, decision)
                    if ok:
                        trade_in = schemas.TradeCreate(
                            symbol=symbol,
                            direction=schemas.TradeDirection(decision.decision.lower()),
                            entry_price=decision.entry_price,
                            stop_loss=decision.stop_loss,
                            take_profit=decision.take_profit,
                            risk_pct=decision.position_size_pct,
                            mode=schemas.TradeMode.paper,
                            ai_decision_id=db_decision.id,
                            rationale=decision.rationale,
                        )
                        await executor.execute_trade(db, trade_in)
                    else:
                        decision.decision = "HOLD"
                        decision.rationale += f" [RISK BLOCKED: {reason}]"
                        db_decision.decision = "HOLD"
                        db_decision.rationale = decision.rationale
                        await db.commit()

                results.append({"symbol": symbol, "decision": decision.decision, "confidence": decision.confidence})

            return results

    return asyncio.run(_analyze())


@celery_app.task
def auto_select_pairs():
    async def _select():
        async with AsyncSessionLocal() as db:
            from app import models
            result = await db.execute(select(models.ActivePair).where(models.ActivePair.selection_mode == "auto"))
            auto_pairs = result.scalars().all()
            if not auto_pairs:
                return {"detail": "No auto-selection pairs configured"}

            aggregator = AnalysisAggregator()
            available = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]
            scored = []
            for sym in available:
                analysis = await aggregator.gather_all(sym)
                score = aggregator._score_pair(analysis)
                scored.append((sym, score))

            scored.sort(key=lambda x: abs(x[1]), reverse=True)
            top = scored[:len(auto_pairs)]

            for idx, pair in enumerate(auto_pairs):
                if idx < len(top):
                    pair.symbol = top[idx][0]

            await db.commit()
            return {"selected": [s for s, _ in top]}

    return asyncio.run(_select())

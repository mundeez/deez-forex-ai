import asyncio
from app.celery_app import celery_app
from app.analysis.aggregator import AnalysisAggregator
from app.ai.openrouter_client import OpenRouterClient
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.database import AsyncSessionLocal
from app import schemas


@celery_app.task
def run_full_analysis():
    async def _analyze():
        async with AsyncSessionLocal() as db:
            aggregator = AnalysisAggregator()
            ai = OpenRouterClient()
            executor = ExecutionService()
            risk = RiskManager()

            analysis = await aggregator.gather_all("EURUSD")
            decision = await ai.get_trade_decision(analysis)

            from app import models
            db_decision = models.AIDecision(
                symbol="EURUSD",
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
                model_used="anthropic/claude-3.5-sonnet",
            )
            db.add(db_decision)
            await db.commit()

            if decision.decision in ("BUY", "SELL"):
                ok, reason = await risk.validate_ai_decision(db, decision)
                if ok:
                    trade_in = schemas.TradeCreate(
                        symbol="EURUSD",
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
            return {"decision": decision.decision, "confidence": decision.confidence}

    return asyncio.run(_analyze())

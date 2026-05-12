from datetime import datetime, timedelta
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models, schemas
from app.config import get_settings
from app.ai.openrouter_client import TradeDecision

settings = get_settings()


class RiskManager:
    async def validate_new_trade(
        self, db: AsyncSession, trade_in: schemas.TradeCreate
    ) -> Tuple[bool, str]:
        if trade_in.risk_pct and trade_in.risk_pct > settings.MAX_RISK_PER_TRADE_PCT:
            return False, f"Risk per trade {trade_in.risk_pct}% exceeds max {settings.MAX_RISK_PER_TRADE_PCT}%"

        today = datetime.utcnow().date()
        start_of_day = datetime.combine(today, datetime.min.time())
        result = await db.execute(
            select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
                models.Trade.status == models.TradeStatus.CLOSED,
                models.Trade.close_time >= start_of_day,
            )
        )
        daily_pnl = result.scalar() or 0
        equity = 10000.0
        daily_loss_pct = abs(daily_pnl) / equity * 100
        if daily_loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            return False, f"Daily loss limit {settings.MAX_DAILY_LOSS_PCT}% reached"

        result = await db.execute(
            select(func.count(models.Trade.id)).where(
                models.Trade.status == models.TradeStatus.OPEN,
                models.Trade.symbol == trade_in.symbol,
            )
        )
        open_count = result.scalar() or 0
        MAX_OPEN_PER_SYMBOL = 7
        if open_count >= MAX_OPEN_PER_SYMBOL:
            return False, f"Max {MAX_OPEN_PER_SYMBOL} open trades per symbol allowed"

        return True, "OK"

    async def validate_ai_decision(
        self, db: AsyncSession, decision: TradeDecision
    ) -> Tuple[bool, str]:
        if decision.confidence < 0.60:
            return False, f"AI confidence {decision.confidence} below 0.60 threshold"
        if decision.risk_reward and decision.risk_reward < 1.0:
            return False, f"Risk/reward {decision.risk_reward} below 1:1 minimum"
        if decision.position_size_pct and decision.position_size_pct > settings.MAX_RISK_PER_TRADE_PCT:
            return False, f"AI suggested risk {decision.position_size_pct}% exceeds limit"

        trade_in = schemas.TradeCreate(
            symbol=decision.symbol or settings.DEFAULT_PAIR,
            direction=schemas.TradeDirection(decision.decision.lower()),
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            risk_pct=decision.position_size_pct,
            mode=schemas.TradeMode.paper,
        )
        return await self.validate_new_trade(db, trade_in)

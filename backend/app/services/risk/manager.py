from datetime import datetime, timedelta
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models, schemas
from app.config import get_settings
from app.ai.openrouter_client import TradeDecision
from app.services.settings_service import get_setting_float, get_setting_int

settings = get_settings()


class RiskManager:
    async def _get_equity(self, db: AsyncSession) -> float:
        result = await db.execute(
            select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
                models.Trade.status == models.TradeStatus.CLOSED
            )
        )
        realized = result.scalar() or 0.0
        result2 = await db.execute(
            select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
                models.Trade.status == models.TradeStatus.OPEN
            )
        )
        unrealized = result2.scalar() or 0.0
        equity_balance = await get_setting_float(db, "equity_balance")
        return equity_balance + realized + unrealized

    async def validate_new_trade(
        self, db: AsyncSession, trade_in: schemas.TradeCreate
    ) -> Tuple[bool, str]:
        max_risk_pct = await get_setting_float(db, "max_risk_per_trade_pct")
        max_risk_abs = await get_setting_float(db, "max_risk_per_trade_abs")
        max_daily_loss = await get_setting_float(db, "max_daily_loss_pct")
        max_open_per_symbol = await get_setting_int(db, "max_open_per_symbol")

        if trade_in.risk_pct and trade_in.risk_pct > max_risk_pct:
            return False, f"Risk per trade {trade_in.risk_pct}% exceeds max {max_risk_pct}%"

        equity = await self._get_equity(db)
        if max_risk_abs > 0 and trade_in.risk_pct:
            risk_amount = equity * (trade_in.risk_pct / 100)
            if risk_amount > max_risk_abs:
                return False, f"Risk amount ${risk_amount:.2f} exceeds max ${max_risk_abs:.2f}"

        today = datetime.utcnow().date()
        start_of_day = datetime.combine(today, datetime.min.time())
        result = await db.execute(
            select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
                models.Trade.status == models.TradeStatus.CLOSED,
                models.Trade.close_time >= start_of_day,
            )
        )
        daily_pnl = result.scalar() or 0
        daily_loss_pct = abs(daily_pnl) / equity * 100 if equity > 0 else 0
        if daily_loss_pct >= max_daily_loss:
            return False, f"Daily loss limit {max_daily_loss}% reached"

        result = await db.execute(
            select(func.count(models.Trade.id)).where(
                models.Trade.status == models.TradeStatus.OPEN,
                models.Trade.symbol == trade_in.symbol,
            )
        )
        open_count = result.scalar() or 0
        if open_count >= max_open_per_symbol:
            return False, f"Max {max_open_per_symbol} open trades per symbol allowed"

        return True, "OK"

    async def validate_ai_decision(
        self, db: AsyncSession, decision: TradeDecision
    ) -> Tuple[bool, str]:
        ai_confidence_threshold = await get_setting_float(db, "ai_confidence_threshold")
        min_risk_reward = await get_setting_float(db, "min_risk_reward")
        max_risk_pct = await get_setting_float(db, "max_risk_per_trade_pct")

        if decision.confidence < ai_confidence_threshold:
            return False, f"AI confidence {decision.confidence} below {ai_confidence_threshold} threshold"
        if decision.risk_reward and decision.risk_reward < min_risk_reward:
            return False, f"Risk/reward {decision.risk_reward} below {min_risk_reward}:1 minimum"
        if decision.position_size_pct and decision.position_size_pct > max_risk_pct:
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

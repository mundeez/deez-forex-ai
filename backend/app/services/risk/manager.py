from datetime import datetime, timedelta
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models, schemas
from app.config import get_settings
from app.ai.openrouter_client import TradeDecision
from app.services.settings_service import get_setting_float, get_setting_int, get_setting

settings = get_settings()

# Strategy-aware defaults (overridable via settings)
STRATEGY_CONFIG = {
    "scalping": {
        "max_risk_pct": 1.0,
        "min_risk_reward": 0.8,
        "ai_confidence_threshold": 0.50,
        "max_open_per_symbol": 5,
        "max_trade_duration_min": 10,
    },
    "day_trading": {
        "max_risk_pct": 1.5,
        "min_risk_reward": 1.2,
        "ai_confidence_threshold": 0.55,
        "max_open_per_symbol": 3,
        "max_trade_duration_min": 120,
    },
    "swing": {
        "max_risk_pct": 2.0,
        "min_risk_reward": 2.0,
        "ai_confidence_threshold": 0.60,
        "max_open_per_symbol": 2,
        "max_trade_duration_min": 1440,
    },
}


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
        return max(equity_balance + realized + unrealized, 1.0)

    async def _get_strategy_mode(self, db: AsyncSession) -> str:
        mode = await get_setting(db, "strategy_mode")
        return mode if mode in STRATEGY_CONFIG else "scalping"

    def _get_strategy_value(self, strategy_mode: str, key: str, db_value: float) -> float:
        """Return strategy default if db setting is 0 or not set, otherwise use db value."""
        if db_value == 0:
            return STRATEGY_CONFIG.get(strategy_mode, {}).get(key, db_value)
        return db_value

    async def validate_new_trade(
        self, db: AsyncSession, trade_in: schemas.TradeCreate
    ) -> Tuple[bool, str]:
        strategy_mode = await self._get_strategy_mode(db)
        sc = STRATEGY_CONFIG.get(strategy_mode, STRATEGY_CONFIG["scalping"])

        max_risk_pct = await get_setting_float(db, "max_risk_per_trade_pct")
        max_risk_pct = self._get_strategy_value(strategy_mode, "max_risk_pct", max_risk_pct)

        max_risk_abs = await get_setting_float(db, "max_risk_per_trade_abs")
        max_daily_loss = await get_setting_float(db, "max_daily_loss_pct")
        max_open_per_symbol = await get_setting_int(db, "max_open_per_symbol")
        max_open_per_symbol = int(self._get_strategy_value(strategy_mode, "max_open_per_symbol", max_open_per_symbol))

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
        strategy_mode = await self._get_strategy_mode(db)
        sc = STRATEGY_CONFIG.get(strategy_mode, STRATEGY_CONFIG["scalping"])

        ai_confidence_threshold = await get_setting_float(db, "ai_confidence_threshold")
        ai_confidence_threshold = self._get_strategy_value(strategy_mode, "ai_confidence_threshold", ai_confidence_threshold)

        min_risk_reward = await get_setting_float(db, "min_risk_reward")
        min_risk_reward = self._get_strategy_value(strategy_mode, "min_risk_reward", min_risk_reward)

        max_risk_pct = await get_setting_float(db, "max_risk_per_trade_pct")
        max_risk_pct = self._get_strategy_value(strategy_mode, "max_risk_pct", max_risk_pct)

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

    def calculate_position_size(self, equity: float, risk_pct: float, entry: float, stop_loss: float) -> float:
        """Calculate lot size based on risk amount and stop distance."""
        if not entry or not stop_loss or entry == stop_loss:
            return 0.01
        risk_amount = equity * (risk_pct / 100)
        sl_dist = abs(entry - stop_loss)
        # pip value approx: 1 standard lot = $10/pip on EURUSD
        # position_size in lots = risk_amount / (sl_dist in pips * $10 per pip per lot)
        # sl_dist for EURUSD at 1.0850: 0.0010 = 10 pips = $100 risk at 0.01 lot... wait
        # Actually: 0.01 lot = $0.10 per pip. 10 pips = $1.00
        # So: position_size = risk_amount / (sl_dist * 100000 * 10) ... no
        # Simpler: sl_dist in price terms. For EURUSD, 1 pip = 0.0001
        # 0.01 lot: 1 pip = $0.10. So for sl_dist pips = sl_dist / 0.0001
        # position_size = risk_amount / (sl_pips * 0.10) * 0.01
        # position_size = risk_amount / (sl_dist / 0.0001 * 0.10) * 0.01
        # = risk_amount / (sl_dist * 10000 * 0.10) * 0.01
        # = risk_amount / (sl_dist * 1000) * 0.01
        # = risk_amount * 0.01 / (sl_dist * 1000)
        # Let's simplify:
        pip_value_per_lot = 10.0  # $10 per pip per standard lot for EURUSD
        sl_pips = sl_dist / 0.0001
        risk_per_lot = sl_pips * pip_value_per_lot
        if risk_per_lot <= 0:
            return 0.01
        lots = risk_amount / risk_per_lot
        # Round down to nearest 0.001 (nano lot) for precision
        lots = max(0.001, min(lots, equity / (entry * 100000)))  # cap by margin (100:1 leverage approx)
        return round(lots, 3)

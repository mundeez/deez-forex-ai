import logging
from datetime import datetime, timedelta
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models, schemas
from app.enums import TradeDirection, TradeMode
from app.config import get_settings
from app.ai.openrouter_client import TradeDecision
from app.services.settings_service import get_setting_float, get_setting_int, get_setting

settings = get_settings()
logger = logging.getLogger("app.services.risk")

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
            direction=TradeDirection(decision.decision.lower()),
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            risk_pct=decision.position_size_pct,
            mode=TradeMode.PAPER,
        )
        return await self.validate_new_trade(db, trade_in)

    async def validate_sl_tp_atr(
        self, db: AsyncSession, entry: float, stop_loss: float, take_profit: float, atr: float
    ) -> Tuple[bool, str]:
        """Validate that SL/TP distances are within acceptable ATR multiples."""
        if not atr or atr <= 0:
            return True, "OK"
        strategy_mode = await self._get_strategy_mode(db)
        sl_dist = abs(entry - stop_loss)
        tp_dist = abs(take_profit - entry)
        sl_atr = sl_dist / atr
        tp_atr = tp_dist / atr

        limits = {
            "scalping": {"sl_min": 0.5, "sl_max": 2.0, "tp_min": 1.0, "tp_max": 3.0},
            "day_trading": {"sl_min": 1.0, "sl_max": 3.0, "tp_min": 2.0, "tp_max": 5.0},
            "swing": {"sl_min": 2.0, "sl_max": 5.0, "tp_min": 3.0, "tp_max": 8.0},
        }
        lim = limits.get(strategy_mode, limits["scalping"])

        if sl_atr < lim["sl_min"]:
            return False, f"SL too tight: {sl_atr:.2f}x ATR (min {lim['sl_min']}x)"
        if sl_atr > lim["sl_max"]:
            return False, f"SL too wide: {sl_atr:.2f}x ATR (max {lim['sl_max']}x)"
        if tp_atr < lim["tp_min"]:
            return False, f"TP too close: {tp_atr:.2f}x ATR (min {lim['tp_min']}x)"
        if tp_atr > lim["tp_max"]:
            return False, f"TP too far: {tp_atr:.2f}x ATR (max {lim['tp_max']}x)"
        return True, "OK"

    async def validate_spread(self, db: AsyncSession, symbol: str, atr: float) -> Tuple[bool, str]:
        """Skip trades when spread is too wide relative to ATR."""
        from app.services.settings_service import get_setting_bool, get_setting_float
        if not await get_setting_bool(db, "spread_filter_enabled"):
            return True, "OK"
        if not atr or atr <= 0:
            return True, "OK"

        # Fetch current price to get spread
        from app.services.data.metaapi_client import MetaApiClient
        client = MetaApiClient()
        try:
            price = await client.get_current_price(symbol)
            spread = abs((price.get("ask") or 0) - (price.get("bid") or 0))
        except Exception:
            logger.warning("Failed to fetch current price for %s during spread validation", symbol, exc_info=True)
            return True, "OK"

        ratio = spread / atr
        max_ratio = await get_setting_float(db, "max_spread_to_atr_ratio")
        if ratio > max_ratio:
            return False, f"Spread {spread:.5f} is {ratio:.2f}x ATR (max {max_ratio}x)"
        return True, "OK"

    async def apply_drawdown_reduction(self, db: AsyncSession, base_position_size: float) -> Tuple[float, str]:
        """Reduce position size if account is in drawdown."""
        from app.services.settings_service import get_setting_bool, get_setting_float
        if not await get_setting_bool(db, "drawdown_guard_enabled"):
            return base_position_size, "OK"

        equity = await self._get_equity(db)
        # Get peak equity from latest snapshot
        result = await db.execute(
            select(models.AccountSnapshot).order_by(models.AccountSnapshot.timestamp.desc()).limit(1)
        )
        snap = result.scalar_one_or_none()
        peak = snap.peak_equity if snap and snap.peak_equity else equity
        peak = max(peak, equity)

        dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0

        if dd_pct >= 30:
            block = await get_setting_bool(db, "drawdown_block_30pct")
            if block:
                return 0.0, f"Trading blocked: drawdown {dd_pct:.1f}% >= 30%"
        if dd_pct >= 20:
            reduce = await get_setting_float(db, "drawdown_reduce_20pct") / 100.0
            return base_position_size * (1 - reduce), f"Position reduced {reduce*100:.0f}%: drawdown {dd_pct:.1f}%"
        if dd_pct >= 10:
            reduce = await get_setting_float(db, "drawdown_reduce_10pct") / 100.0
            return base_position_size * (1 - reduce), f"Position reduced {reduce*100:.0f}%: drawdown {dd_pct:.1f}%"
        return base_position_size, "OK"

    async def validate_correlation(self, db: AsyncSession, symbol: str) -> Tuple[bool, str]:
        """Prevent opening highly correlated pairs simultaneously."""
        from app.services.settings_service import get_setting_bool, get_setting_float
        if not await get_setting_bool(db, "correlation_guard_enabled"):
            return True, "OK"

        # Simple correlation matrix for major pairs
        CORR = {
            "EURUSD": {"GBPUSD": 0.85, "AUDUSD": 0.75, "NZDUSD": 0.70},
            "GBPUSD": {"EURUSD": 0.85, "AUDUSD": 0.65, "NZDUSD": 0.60},
            "USDJPY": {"USDCAD": 0.70, "USDCHF": 0.80},
            "USDCAD": {"USDJPY": 0.70, "USDCHF": 0.65},
            "USDCHF": {"USDJPY": 0.80, "USDCAD": 0.65},
            "AUDUSD": {"EURUSD": 0.75, "GBPUSD": 0.65, "NZDUSD": 0.80},
            "NZDUSD": {"EURUSD": 0.70, "GBPUSD": 0.60, "AUDUSD": 0.80},
            "EURGBP": {"EURUSD": 0.50, "GBPUSD": 0.50},
            "GBPJPY": {"GBPUSD": 0.50, "USDJPY": 0.60},
            "XAUUSD": {"USDJPY": -0.40, "EURUSD": 0.30},
        }

        max_corr = await get_setting_float(db, "max_correlation_allowed")
        result = await db.execute(
            select(models.Trade.symbol).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_symbols = [r[0] for r in result.all()]

        for osym in open_symbols:
            corr = CORR.get(symbol, {}).get(osym) or CORR.get(osym, {}).get(symbol)
            if corr and abs(corr) >= max_corr:
                return False, f"Correlation {corr:.2f} with {osym} exceeds limit {max_corr}"
        return True, "OK"

    def calculate_position_size(self, equity: float, risk_pct: float, entry: float, stop_loss: float) -> float:
        """Calculate lot size based on risk amount and stop distance."""
        if not entry or not stop_loss or entry == stop_loss:
            return 0.01
        risk_amount = equity * (risk_pct / 100)
        sl_dist = abs(entry - stop_loss)
        pip_value_per_lot = 10.0
        sl_pips = sl_dist / 0.0001
        risk_per_lot = sl_pips * pip_value_per_lot
        if risk_per_lot <= 0:
            return 0.01
        lots = risk_amount / risk_per_lot
        lots = max(0.001, min(lots, equity / (entry * 100000)))
        return round(lots, 3)

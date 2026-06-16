"""ExitEvaluator — rules-based exit layer for open positions.

Evaluates every open trade against configurable exit rules and returns
recommendations.  Rules are applied in priority order; the first triggered
rule wins.  The evaluator can also directly execute exits via the executor.

Rules (priority order):
1. Profit-lock      — lock gains after 2R+ if price gives back X%
2. Pre-news exit    — close before high-impact economic events
3. Technical flip   — EMA-9 crosses against trade direction
4. Staleness        — trade open too long with no meaningful progress
5. Breakeven ladder — move SL to entry at 0.5R, to 0.3R profit at 1.0R
6. Partial profit   — take 33% at 1R, 33% at 1.5R, trail remainder

Usage::
    evaluator = ExitEvaluator()
    recs = await evaluator.evaluate_all(db)
    for rec in recs:
        if rec.action == "close_now":
            await evaluator.execute_exit(db, rec)
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import models, schemas
from app.enums import TradeDirection, TradeStatus
from app.services.execution.executor import ExecutionService
from app.services.settings_service import get_setting_bool, get_setting_float
from app.services.instruments import pips, pip_size
from app.utils.time import utc_now, ensure_aware

logger = logging.getLogger("app.services.exit_evaluator")


class ExitAction(Enum):
    HOLD = "hold"
    CLOSE_NOW = "close_now"
    MOVE_SL = "move_sl"
    TAKE_PARTIAL = "take_partial"


@dataclass
class ExitRecommendation:
    trade_id: int
    symbol: str
    action: ExitAction
    reason: str
    confidence: float = 1.0          # 0-1, higher = more certain
    suggested_sl: Optional[float] = None
    suggested_tp: Optional[float] = None
    close_pct: Optional[float] = None  # for partial exits
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExitEvaluator:
    """Rules-based exit evaluation engine."""

    def __init__(self, executor: ExecutionService = None):
        self.executor = executor or ExecutionService()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_r_multiple(trade: models.Trade, current_price: float) -> float:
        """Return current R-multiple (profit / initial risk)."""
        if not trade.entry_price or not trade.stop_loss or trade.entry_price == trade.stop_loss:
            return 0.0
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk == 0:
            return 0.0
        if trade.direction == TradeDirection.BUY.value:
            profit = current_price - trade.entry_price
        else:
            profit = trade.entry_price - current_price
        return profit / risk

    @staticmethod
    def _compute_max_favourable_r(trade: models.Trade) -> float:
        """Return max R ever reached (based on highest/lowest price seen)."""
        if not trade.entry_price or not trade.stop_loss or trade.entry_price == trade.stop_loss:
            return 0.0
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk == 0:
            return 0.0
        if trade.direction == TradeDirection.BUY.value:
            best_price = trade.highest_price_seen or trade.entry_price
            profit = best_price - trade.entry_price
        else:
            best_price = trade.lowest_price_seen or trade.entry_price
            profit = trade.entry_price - best_price
        return profit / risk

    @staticmethod
    def _holding_minutes(trade: models.Trade) -> float:
        if not trade.open_time:
            return 0.0
        return (utc_now() - ensure_aware(trade.open_time)).total_seconds() / 60.0

    # ------------------------------------------------------------------
    # Rule: Profit-lock
    # ------------------------------------------------------------------

    async def _rule_profit_lock(
        self, trade: models.Trade, current_price: float, giveback_pct: float
    ) -> Optional[ExitRecommendation]:
        """If trade reached 2R+ and then gives back giveback_pct of max profit, exit."""
        max_r = self._compute_max_favourable_r(trade)
        if max_r < 1.99:
            return None
        current_r = self._compute_r_multiple(trade, current_price)
        # Giveback is measured as drop from peak R
        if current_r < max_r * (1 - giveback_pct / 100):
            return ExitRecommendation(
                trade_id=trade.id,
                symbol=trade.symbol,
                action=ExitAction.CLOSE_NOW,
                reason=f"profit_lock: peak {max_r:.1f}R → current {current_r:.1f}R (giveback > {giveback_pct}%)",
                confidence=min(0.5 + (max_r - current_r) * 0.1, 0.95),
                metadata={"peak_r": round(max_r, 2), "current_r": round(current_r, 2)},
            )
        return None

    # ------------------------------------------------------------------
    # Rule: Pre-news exit
    # ------------------------------------------------------------------

    async def _rule_pre_news(
        self, trade: models.Trade, minutes_before: float = 5.0
    ) -> Optional[ExitRecommendation]:
        """Close before high-impact news (next 5 min by default)."""
        # EconomicCalendar table was added in Sprint 1
        now = utc_now()
        window_end = now + timedelta(minutes=minutes_before)
        # Query upcoming high-impact events for this symbol's currency
        currencies = set()
        sym = trade.symbol.upper()
        # Simple currency extraction
        if len(sym) == 6:
            currencies = {sym[:3], sym[3:]}
        elif "USD" in sym:
            currencies = {"USD"}
        elif "EUR" in sym:
            currencies = {"EUR"}
        elif "GBP" in sym:
            currencies = {"GBP"}
        elif "JPY" in sym:
            currencies = {"JPY"}
        elif "AUD" in sym:
            currencies = {"AUD"}
        elif "CAD" in sym:
            currencies = {"CAD"}
        elif "CHF" in sym:
            currencies = {"CHF"}
        elif "NZD" in sym:
            currencies = {"NZD"}

        if not currencies:
            return None

        # Check if any high-impact event is imminent
        # Note: we use a lightweight check; the full query would join EconomicCalendar
        # For now, rely on a cached Redis key set by the data ingestion layer
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url("redis://redis:6379/0", decode_responses=True)
            for curr in currencies:
                key = f"news:high_impact:{curr.lower()}"
                ts = await r.get(key)
                if ts:
                    event_time = datetime.fromisoformat(ts)
                    if now <= event_time <= window_end:
                        await r.close()
                        return ExitRecommendation(
                            trade_id=trade.id,
                            symbol=trade.symbol,
                            action=ExitAction.CLOSE_NOW,
                            reason=f"pre_news: high-impact {curr} event at {event_time:%H:%M}",
                            confidence=0.85,
                        )
            await r.close()
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Rule: Technical flip (EMA-9 cross)
    # ------------------------------------------------------------------

    async def _rule_technical_flip(
        self, trade: models.Trade, current_price: float
    ) -> Optional[ExitRecommendation]:
        """Exit if short-term trend flips against position."""
        # Fetch latest technical snapshot from ai_decisions or cache
        # For now, use a simple heuristic: if price crossed below EMA-9 for BUY,
        # or above EMA-9 for SELL, trigger exit.
        # In production this would read from the latest 1h indicator snapshot.
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url("redis://redis:6379/0", decode_responses=True)
            ema9 = await r.get(f"indicator:ema9:{trade.symbol}:1h")
            await r.close()
            if not ema9:
                return None
            ema9 = float(ema9)
            if trade.direction == TradeDirection.BUY.value and current_price < ema9:
                return ExitRecommendation(
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    action=ExitAction.CLOSE_NOW,
                    reason=f"technical_flip: price {current_price:.5f} < EMA-9 {ema9:.5f}",
                    confidence=0.7,
                )
            if trade.direction == TradeDirection.SELL.value and current_price > ema9:
                return ExitRecommendation(
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    action=ExitAction.CLOSE_NOW,
                    reason=f"technical_flip: price {current_price:.5f} > EMA-9 {ema9:.5f}",
                    confidence=0.7,
                )
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Rule: Staleness
    # ------------------------------------------------------------------

    async def _rule_staleness(
        self, trade: models.Trade, max_minutes: float, min_r_progress: float = 0.3
    ) -> Optional[ExitRecommendation]:
        """Exit if trade is stale: open too long with less than min_r_progress R."""
        held = self._holding_minutes(trade)
        if held < max_minutes:
            return None
        # Need current price to assess progress
        # We skip if we can't compute R; caller passes price
        return None  # price-based staleness is checked in evaluate_trade

    def _rule_staleness_with_price(
        self, trade: models.Trade, current_price: float, max_minutes: float, min_r_progress: float = 0.3
    ) -> Optional[ExitRecommendation]:
        held = self._holding_minutes(trade)
        if held < max_minutes:
            return None
        current_r = self._compute_r_multiple(trade, current_price)
        if abs(current_r) < min_r_progress:
            return ExitRecommendation(
                trade_id=trade.id,
                symbol=trade.symbol,
                action=ExitAction.CLOSE_NOW,
                reason=f"staleness: open {held:.0f}min with only {current_r:.1f}R progress",
                confidence=0.6,
            )
        return None

    # ------------------------------------------------------------------
    # Rule: Breakeven + SL ladder
    # ------------------------------------------------------------------

    def _rule_sl_ladder(
        self, trade: models.Trade, current_price: float
    ) -> Optional[ExitRecommendation]:
        """Dynamic SL: BE at 0.5R, 0.3R profit lock at 1.0R, etc."""
        if not trade.entry_price or not trade.stop_loss:
            return None
        r = self._compute_r_multiple(trade, current_price)
        entry = trade.entry_price
        sl = trade.stop_loss
        risk = abs(entry - sl)
        if risk == 0:
            return None

        # Already at or past BE — check higher rungs
        if trade.direction == TradeDirection.BUY.value:
            # Rung 1: at 0.5R → move SL to entry (breakeven)
            if r >= 0.49 and sl < entry:
                return ExitRecommendation(
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    action=ExitAction.MOVE_SL,
                    reason=f"sl_ladder: 0.5R reached ({r:.2f}R) → SL to entry",
                    suggested_sl=round(entry, 5),
                    confidence=0.9,
                )
            # Rung 2: at 1.0R → lock 0.3R profit
            if r >= 0.99:
                new_sl = entry + risk * 0.3
                if sl < new_sl:
                    return ExitRecommendation(
                        trade_id=trade.id,
                        symbol=trade.symbol,
                        action=ExitAction.MOVE_SL,
                        reason=f"sl_ladder: 1.0R reached ({r:.2f}R) → lock 0.3R profit",
                        suggested_sl=round(new_sl, 5),
                        confidence=0.9,
                    )
            # Rung 3: at 2.0R → lock 1.0R profit
            if r >= 1.99:
                new_sl = entry + risk * 1.0
                if sl < new_sl:
                    return ExitRecommendation(
                        trade_id=trade.id,
                        symbol=trade.symbol,
                        action=ExitAction.MOVE_SL,
                        reason=f"sl_ladder: 2.0R reached ({r:.2f}R) → lock 1.0R profit",
                        suggested_sl=round(new_sl, 5),
                        confidence=0.9,
                    )
        else:
            # SELL direction
            if r >= 0.5 and sl > entry:
                return ExitRecommendation(
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    action=ExitAction.MOVE_SL,
                    reason=f"sl_ladder: 0.5R reached ({r:.2f}R) → SL to entry",
                    suggested_sl=round(entry, 5),
                    confidence=0.9,
                )
            if r >= 0.99:
                new_sl = entry - risk * 0.3
                if sl > new_sl:
                    return ExitRecommendation(
                        trade_id=trade.id,
                        symbol=trade.symbol,
                        action=ExitAction.MOVE_SL,
                        reason=f"sl_ladder: 1.0R reached ({r:.2f}R) → lock 0.3R profit",
                        suggested_sl=round(new_sl, 5),
                        confidence=0.9,
                    )
            if r >= 1.99:
                new_sl = entry - risk * 1.0
                if sl > new_sl:
                    return ExitRecommendation(
                        trade_id=trade.id,
                        symbol=trade.symbol,
                        action=ExitAction.MOVE_SL,
                        reason=f"sl_ladder: 2.0R reached ({r:.2f}R) → lock 1.0R profit",
                        suggested_sl=round(new_sl, 5),
                        confidence=0.9,
                    )
        return None

    # ------------------------------------------------------------------
    # Rule: Partial profit taking
    # ------------------------------------------------------------------

    def _rule_partial_profit(
        self, trade: models.Trade, current_price: float
    ) -> Optional[ExitRecommendation]:
        """33% at 1R, 33% at 1.5R, trail remainder."""
        if trade.closed_portion and trade.closed_portion >= 0.66:
            return None  # already took both partials
        r = self._compute_r_multiple(trade, current_price)
        if r >= 1.49 and trade.closed_portion and trade.closed_portion < 0.66:
            return ExitRecommendation(
                trade_id=trade.id,
                symbol=trade.symbol,
                action=ExitAction.TAKE_PARTIAL,
                reason=f"partial_profit: 1.5R reached ({r:.2f}R) → close 33%",
                close_pct=0.33,
                confidence=0.85,
            )
        if r >= 0.99 and (not trade.closed_portion or trade.closed_portion < 0.33):
            return ExitRecommendation(
                trade_id=trade.id,
                symbol=trade.symbol,
                action=ExitAction.TAKE_PARTIAL,
                reason=f"partial_profit: 1.0R reached ({r:.2f}R) → close 33%",
                close_pct=0.33,
                confidence=0.85,
            )
        return None

    # ------------------------------------------------------------------
    # Main evaluation
    # ------------------------------------------------------------------

    async def evaluate_trade(
        self,
        db: AsyncSession,
        trade: models.Trade,
        current_price: float,
        settings_cache: Optional[Dict[str, Any]] = None,
    ) -> ExitRecommendation:
        """Evaluate a single open trade and return the highest-priority recommendation."""
        s = settings_cache or {}
        if not s:
            s = {
                "exit_rules_enabled": await get_setting_bool(db, "exit_rules_enabled"),
                "profit_lock_enabled": await get_setting_bool(db, "profit_lock_enabled"),
                "profit_lock_giveback_pct": await get_setting_float(db, "profit_lock_giveback_pct"),
                "pre_news_exit_enabled": await get_setting_bool(db, "pre_news_exit_enabled"),
                "technical_flip_enabled": await get_setting_bool(db, "technical_flip_enabled"),
                "staleness_enabled": await get_setting_bool(db, "staleness_enabled"),
                "staleness_max_min": await get_setting_float(db, "staleness_max_min"),
                "sl_ladder_enabled": await get_setting_bool(db, "sl_ladder_enabled"),
                "partial_profit_enabled": await get_setting_bool(db, "partial_profit_enabled"),
            }

        if not s.get("exit_rules_enabled", True):
            return ExitRecommendation(
                trade_id=trade.id, symbol=trade.symbol, action=ExitAction.HOLD, reason="exit_rules_disabled"
            )

        # Priority order: profit_lock > pre_news > technical_flip > staleness > sl_ladder > partial_profit
        if s.get("profit_lock_enabled", True):
            rec = await self._rule_profit_lock(
                trade, current_price, s.get("profit_lock_giveback_pct", 50.0)
            )
            if rec:
                return rec

        if s.get("pre_news_exit_enabled", True):
            rec = await self._rule_pre_news(trade)
            if rec:
                return rec

        if s.get("technical_flip_enabled", True):
            rec = await self._rule_technical_flip(trade, current_price)
            if rec:
                return rec

        if s.get("staleness_enabled", True):
            rec = self._rule_staleness_with_price(
                trade, current_price, s.get("staleness_max_min", 120.0)
            )
            if rec:
                return rec

        if s.get("sl_ladder_enabled", True):
            rec = self._rule_sl_ladder(trade, current_price)
            if rec:
                return rec

        if s.get("partial_profit_enabled", True):
            rec = self._rule_partial_profit(trade, current_price)
            if rec:
                return rec

        return ExitRecommendation(
            trade_id=trade.id, symbol=trade.symbol, action=ExitAction.HOLD, reason="no_rule_triggered"
        )

    async def evaluate_all(
        self, db: AsyncSession
    ) -> Tuple[List[ExitRecommendation], List[models.Trade]]:
        """Evaluate all open trades. Returns (recommendations, updated_trades)."""
        result = await db.execute(
            select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_trades = result.scalars().all()
        if not open_trades:
            return [], []

        # Cache settings once per batch
        settings_cache = {
            "exit_rules_enabled": await get_setting_bool(db, "exit_rules_enabled"),
            "profit_lock_enabled": await get_setting_bool(db, "profit_lock_enabled"),
            "profit_lock_giveback_pct": await get_setting_float(db, "profit_lock_giveback_pct"),
            "pre_news_exit_enabled": await get_setting_bool(db, "pre_news_exit_enabled"),
            "technical_flip_enabled": await get_setting_bool(db, "technical_flip_enabled"),
            "staleness_enabled": await get_setting_bool(db, "staleness_enabled"),
            "staleness_max_min": await get_setting_float(db, "staleness_max_min"),
            "sl_ladder_enabled": await get_setting_bool(db, "sl_ladder_enabled"),
            "partial_profit_enabled": await get_setting_bool(db, "partial_profit_enabled"),
        }
        if not settings_cache["exit_rules_enabled"]:
            return [], list(open_trades)

        # Fetch all prices in parallel
        symbols = list({t.symbol for t in open_trades})
        prices_map = await self.executor._fetch_prices_batch(self.executor._get_client(), symbols)

        recommendations: List[ExitRecommendation] = []
        updated_trades: List[models.Trade] = []

        for trade in open_trades:
            price_data = prices_map.get(trade.symbol)
            if not price_data:
                continue
            current = price_data.get("bid") if trade.direction == TradeDirection.BUY.value else price_data.get("ask")
            if not current:
                continue

            # Update price-path extremes
            if trade.highest_price_seen is None or current > trade.highest_price_seen:
                trade.highest_price_seen = current
            if trade.lowest_price_seen is None or current < trade.lowest_price_seen:
                trade.lowest_price_seen = current

            rec = await self.evaluate_trade(db, trade, current, settings_cache)
            if rec.action != ExitAction.HOLD:
                recommendations.append(rec)
            updated_trades.append(trade)

        await db.commit()
        return recommendations, updated_trades

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_exit(
        self, db: AsyncSession, rec: ExitRecommendation
    ) -> Optional[models.Trade]:
        """Execute a close or partial-close recommendation."""
        if rec.action == ExitAction.HOLD:
            return None

        if rec.action == ExitAction.MOVE_SL:
            result = await db.execute(
                select(models.Trade).where(models.Trade.id == rec.trade_id).with_for_update()
            )
            trade = result.scalar_one_or_none()
            if trade and trade.status == models.TradeStatus.OPEN and rec.suggested_sl is not None:
                trade.stop_loss = rec.suggested_sl
                # Log the adjustment
                note = f" | SL moved: {rec.reason}"
                trade.rationale = (trade.rationale or "") + note
                await db.commit()
                logger.info("Trade %s SL moved to %.5f (%s)", trade.id, rec.suggested_sl, rec.reason)
            return trade

        if rec.action == ExitAction.TAKE_PARTIAL:
            result = await db.execute(
                select(models.Trade).where(models.Trade.id == rec.trade_id).with_for_update()
            )
            trade = result.scalar_one_or_none()
            if not trade or trade.status != models.TradeStatus.OPEN:
                return None
            close_pct = rec.close_pct or 0.33
            portion = trade.position_size * close_pct
            if portion <= 0:
                return None

            # Reduce position size, record partial PnL
            price = await self.executor._get_live_price(trade.symbol)
            if not price:
                return None
            current = price.get("bid") if trade.direction == TradeDirection.BUY.value else price.get("ask")
            if not current:
                return None

            is_buy = trade.direction == TradeDirection.BUY.value
            partial_pnl = pnl_usd(trade.symbol, is_buy, trade.entry_price, current, portion)
            trade.partial_pnl = (trade.partial_pnl or 0.0) + (partial_pnl or 0.0)
            trade.partial_profit_pnl = trade.partial_pnl
            trade.position_size = trade.position_size - portion
            trade.closed_portion = (trade.closed_portion or 0.0) + close_pct
            trade.partial_tp_hit = True

            note = f" | Partial close: {rec.reason} ({close_pct*100:.0f}% @ {current:.5f})"
            trade.rationale = (trade.rationale or "") + note

            await db.commit()
            logger.info(
                "Trade %s partial exit %.0f%% @ %.5f (pnl=%.2f)",
                trade.id, close_pct * 100, current, partial_pnl or 0,
            )

            # If fully closed
            if trade.position_size <= 0.001:
                trade = await self.executor.close_trade(db, trade.id, current, rec.reason)
            return trade

        if rec.action == ExitAction.CLOSE_NOW:
            price = await self.executor._get_live_price(rec.symbol)
            if not price:
                return None
            current = price.get("bid") if trade.direction == TradeDirection.BUY.value else price.get("ask")
            if not current:
                return None
            trade = await self.executor.close_trade(db, rec.trade_id, current, rec.reason)
            return trade

        return None

    async def execute_all_recommendations(
        self, db: AsyncSession, recommendations: List[ExitRecommendation]
    ) -> List[models.Trade]:
        """Execute a batch of recommendations."""
        executed: List[models.Trade] = []
        for rec in recommendations:
            try:
                trade = await self.execute_exit(db, rec)
                if trade:
                    executed.append(trade)
            except Exception:
                logger.warning("Failed to execute exit for trade %s", rec.trade_id, exc_info=True)
        return executed


# ------------------------------------------------------------------
# Exit quality scoring
# ------------------------------------------------------------------

def compute_exit_quality_score(trade: models.Trade) -> float:
    """Score how well the exit was executed (0-100)."""
    if trade.status != models.TradeStatus.CLOSED:
        return 0.0
    score = 50.0  # baseline

    # 1. Profit vs MFE (did we capture most of the move?)
    if trade.peak_pnl and trade.pnl:
        capture = trade.pnl / max(trade.peak_pnl, 0.01)
        score += capture * 30  # up to +30

    # 2. R-multiple (reward relative to risk)
    if trade.entry_price and trade.stop_loss and trade.exit_price:
        risk = abs(trade.entry_price - trade.stop_loss)
        if risk > 0:
            if trade.direction == TradeDirection.BUY.value:
                profit = trade.exit_price - trade.entry_price
            else:
                profit = trade.entry_price - trade.exit_price
            r = profit / risk
            if r >= 1.99:
                score += 10
            elif r >= 0.99:
                score += 5
            elif r < 0:
                score -= 10

    # 3. Holding time efficiency (profit per minute)
    if trade.actual_holding_min and trade.actual_holding_min > 0 and trade.pnl:
        eff = trade.pnl / trade.actual_holding_min
        if eff > 0.5:
            score += 5
        elif eff < -0.1:
            score -= 5

    # 4. Partial profit bonus
    if trade.partial_tp_hit:
        score += 5

    return max(0.0, min(100.0, score))

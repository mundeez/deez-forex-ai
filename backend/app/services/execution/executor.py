import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from app import models, schemas
from app.enums import TradeDirection, TradeMode, DataProvider
from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
from app.config import get_settings
from app.services.settings_service import get_setting_int, get_setting_bool, get_setting_float
from app.utils.time import utc_now, ensure_aware
from app.services.instruments import pnl_usd, pips
from app.services.sessions import classify_session

settings = get_settings()
logger = logging.getLogger("app.services.execution")


async def compute_live_unrealized(db: AsyncSession) -> float:
    """Calculate live unrealized P&L for all open trades using current market prices."""
    from app.services.data.metaapi_client import MetaApiClient
    from app.services.data.mt5_zmq_client import MT5ZMQClient

    result = await db.execute(
        select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
    )
    open_trades = result.scalars().all()
    if not open_trades:
        return 0.0

    # Batch fetch prices for all open trade symbols
    symbols = list({t.symbol for t in open_trades})
    metaapi = MetaApiClient()
    mt5_zmq = MT5ZMQClient()
    client = mt5_zmq if settings.DATA_PROVIDER == DataProvider.MT5_ZMQ else metaapi
    other = metaapi if client == mt5_zmq else mt5_zmq

    import asyncio
    coros = [client.get_current_price(s) for s in symbols]
    results = await asyncio.gather(*coros, return_exceptions=True)
    prices_map = {}
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception):
            logger.warning("Primary price fetch failed for unrealized P&L %s: %s", sym, res)
        else:
            prices_map[sym] = res

    # Fallback for missing symbols
    missing = [s for s in symbols if s not in prices_map]
    if missing:
        fallback_coros = [other.get_current_price(s) for s in missing]
        fallback_results = await asyncio.gather(*fallback_coros, return_exceptions=True)
        for sym, res in zip(missing, fallback_results):
            if not isinstance(res, Exception):
                prices_map[sym] = res

    total_unrealized = 0.0
    for trade in open_trades:
        price_data = prices_map.get(trade.symbol)
        if not price_data:
            continue
        current = price_data.get("bid") if trade.direction == models.TradeDirection.SELL.value else price_data.get("ask")
        if not current or not trade.entry_price:
            continue
        is_buy = trade.direction == models.TradeDirection.BUY.value
        pnl = pnl_usd(trade.symbol, is_buy, trade.entry_price, current, trade.position_size or 0.01)
        total_unrealized += pnl
    return total_unrealized


class ExecutionService:
    def __init__(self):
        self.metaapi = MetaApiClient()
        self.mt5_zmq = MT5ZMQClient()

    def _get_client(self, provider: schemas.DataProvider = None):
        provider = provider or settings.DATA_PROVIDER
        if provider == DataProvider.MT5_ZMQ:
            return self.mt5_zmq
        return self.metaapi

    async def _get_live_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch live price: MT5 first, then MetaAPI, then None."""
        try:
            price = await self.mt5_zmq.get_current_price(symbol)
            if price.get("bid") is not None:
                return price
        except Exception:
            pass
        try:
            price = await self.metaapi.get_current_price(symbol)
            if price.get("bid") is not None:
                return price
        except Exception:
            pass
        return None

    def _apply_paper_slippage(self, price: float, direction: str, symbol: str) -> float:
        """Simulate realistic slippage for paper trades."""
        import random
        from app.services.instruments import pip_size
        pip = pip_size(symbol)
        # Slippage: 0-2 pips against the trade direction
        slip_pips = random.uniform(0, 2.0)
        slip_price = slip_pips * pip
        if direction == "buy":
            return price + slip_price  # worse fill for buyer
        return price - slip_price  # worse fill for seller

    async def execute_trade(self, db: AsyncSession, trade_in: schemas.TradeCreate, position_size: float = None, strategy_mode: str = "scalping", trailing_distance: float = None) -> models.Trade:
        now = utc_now()
        client = self._get_client(trade_in.provider)
        size = position_size or trade_in.position_size or 0.01
        trade = models.Trade(
            symbol=trade_in.symbol,
            direction=trade_in.direction.value,
            status=models.TradeStatus.OPEN,
            mode=trade_in.mode.value,
            strategy_mode=strategy_mode,
            entry_price=trade_in.entry_price,
            stop_loss=trade_in.stop_loss,
            take_profit=trade_in.take_profit,
            position_size=size,
            original_position_size=size,
            risk_pct=trade_in.risk_pct,
            ai_decision_id=trade_in.ai_decision_id,
            open_time=now,
            session_at_open=classify_session(now),
            rationale=trade_in.rationale,
            provider=trade_in.provider.value,
            trailing_stop_distance=trailing_distance,
        )

        is_live = trade_in.mode == TradeMode.LIVE
        is_metaapi = trade_in.provider == DataProvider.METAAPI
        has_meta_token = bool(settings.META_API_TOKEN)

        if is_live and (has_meta_token if is_metaapi else True):
            order = {
                "symbol": trade_in.symbol,
                "actionType": "ORDER_TYPE_BUY" if trade_in.direction == TradeDirection.BUY else "ORDER_TYPE_SELL",
                "volume": trade.position_size,
                "stopLoss": trade_in.stop_loss,
                "takeProfit": trade_in.take_profit,
            }
            resp = await client.place_trade(order)
            trade.meta_order_id = resp.get("id")
        else:
            trade.mode = models.TradeMode.PAPER
            trade.meta_order_id = f"paper-{now.strftime('%Y%m%d%H%M%S')}-{trade_in.symbol}"
            # Realistic paper fill: use live MT5 price + slippage
            live_price = await self._get_live_price(trade_in.symbol)
            if live_price:
                is_buy = trade_in.direction == TradeDirection.BUY
                raw_price = live_price.get("ask") if is_buy else live_price.get("bid")
                if raw_price:
                    trade.entry_price = self._apply_paper_slippage(
                        raw_price, trade_in.direction.value, trade_in.symbol
                    )

        db.add(trade)
        await db.commit()
        await db.refresh(trade)
        return trade

    async def close_trade(self, db: AsyncSession, trade_id: int, exit_price: float, close_reason: str = "sl_tp") -> models.Trade:
        # Use SELECT FOR UPDATE to prevent race conditions when multiple
        # tasks try to close the same trade simultaneously.
        result = await db.execute(
            select(models.Trade)
            .where(models.Trade.id == trade_id)
            .with_for_update()
        )
        trade: Optional[models.Trade] = result.scalar_one_or_none()
        if not trade:
            raise ValueError(f"Trade {trade_id} not found")
        if trade.status != models.TradeStatus.OPEN:
            logger.info("Trade %s already closed (status=%s), skipping", trade_id, trade.status)
            return trade

        trade.exit_price = exit_price
        trade.status = models.TradeStatus.CLOSED
        trade.close_time = utc_now()
        trade.close_reason = close_reason
        if trade.rationale:
            trade.rationale += f" | Close reason: {close_reason}"
        else:
            trade.rationale = f"Close reason: {close_reason}"

        is_buy = trade.direction == models.TradeDirection.BUY.value
        size = trade.position_size or 0.01
        entry = trade.entry_price or exit_price

        # Realistic paper exit: if exit_price came from SL/TP, try to use live price + slippage
        if trade.mode == models.TradeMode.PAPER.value:
            live_price = await self._get_live_price(trade.symbol)
            if live_price:
                # For BUY: exit at bid; for SELL: exit at ask
                raw_exit = live_price.get("bid") if is_buy else live_price.get("ask")
                if raw_exit:
                    exit_price = self._apply_paper_slippage(
                        raw_exit, "sell" if is_buy else "buy", trade.symbol
                    )

        trade.pnl = pnl_usd(trade.symbol, is_buy, trade.entry_price, exit_price, size)
        diff = (exit_price - entry) if is_buy else (entry - exit_price)
        trade.pnl_pct = (diff / entry) * 100 if entry else 0

        # Exit-timing analytics: holding time, session, MFE/MAE, peak PnL.
        if trade.open_time and trade.close_time:
            trade.actual_holding_min = (ensure_aware(trade.close_time) - ensure_aware(trade.open_time)).total_seconds() / 60.0
        trade.session_at_close = classify_session(trade.close_time)
        if trade.session_at_open is None:
            trade.session_at_open = classify_session(trade.open_time)
        hi, lo = trade.highest_price_seen, trade.lowest_price_seen
        if is_buy:
            fav = hi if hi is not None else max(entry, exit_price)
            adv = lo if lo is not None else min(entry, exit_price)
        else:
            fav = lo if lo is not None else min(entry, exit_price)
            adv = hi if hi is not None else max(entry, exit_price)
        trade.mfe_pips = pips(trade.symbol, (fav - entry) if is_buy else (entry - fav))
        trade.mae_pips = pips(trade.symbol, (entry - adv) if is_buy else (adv - entry))
        trade.peak_pnl = pnl_usd(trade.symbol, is_buy, entry, fav, size)

        if trade.meta_order_id and trade.mode == models.TradeMode.LIVE.value:
            client = self._get_client(schemas.DataProvider(trade.provider))
            await client.close_position(trade.meta_order_id)

        await db.commit()
        await db.refresh(trade)
        return trade

    async def _fetch_prices_batch(self, client, symbols: list) -> dict:
        """Fetch prices for multiple symbols in parallel."""
        import asyncio
        prices = {}
        # Deduplicate symbols
        unique_symbols = list(set(symbols))
        coros = [client.get_current_price(s) for s in unique_symbols]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for sym, res in zip(unique_symbols, results):
            if isinstance(res, Exception):
                logger.warning("Batch price fetch failed for %s: %s", sym, res)
                prices[sym] = None
            else:
                prices[sym] = res
        return prices

    async def check_and_close_positions(self, db: AsyncSession):
        """Check SL/TP hits and close positions. Fetches all prices in parallel."""
        client = self._get_client()
        result = await db.execute(
            select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_trades = result.scalars().all()
        if not open_trades:
            return []

        # Batch fetch all prices in parallel (eliminates N+1 API calls)
        symbols = [t.symbol for t in open_trades]
        prices_map = await self._fetch_prices_batch(client, symbols)

        closed = []
        for trade in open_trades:
            price_data = prices_map.get(trade.symbol)
            if not price_data:
                continue
            sym_bid = price_data.get("bid")
            sym_ask = price_data.get("ask")
            if not sym_bid or not sym_ask:
                continue

            price = sym_bid if trade.direction == models.TradeDirection.BUY.value else sym_ask
            # Track price-path extremes on every open trade (for MFE/MAE at close)
            if trade.highest_price_seen is None or price > trade.highest_price_seen:
                trade.highest_price_seen = price
            if trade.lowest_price_seen is None or price < trade.lowest_price_seen:
                trade.lowest_price_seen = price
            if (trade.direction == models.TradeDirection.BUY.value and price <= trade.stop_loss) or \
               (trade.direction == models.TradeDirection.SELL.value and price >= trade.stop_loss):
                closed_trade = await self.close_trade(db, trade.id, price, "stop_loss")
                closed.append(closed_trade)
            elif (trade.direction == models.TradeDirection.BUY.value and price >= trade.take_profit) or \
                 (trade.direction == models.TradeDirection.SELL.value and price <= trade.take_profit):
                closed_trade = await self.close_trade(db, trade.id, price, "take_profit")
                closed.append(closed_trade)
        # Persist price-path extremes for trades that stayed open this cycle
        await db.commit()
        return closed

    async def check_and_close_time_based_positions(self, db: AsyncSession):
        """Close trades that have exceeded their max duration based on strategy mode."""
        result = await db.execute(
            select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_trades = result.scalars().all()
        if not open_trades:
            return []
        client = self._get_client()
        now = utc_now()

        # Batch fetch all prices in parallel
        symbols = [t.symbol for t in open_trades]
        prices_map = await self._fetch_prices_batch(client, symbols)

        closed = []
        for trade in open_trades:
            strategy_mode = trade.strategy_mode or "scalping"
            max_duration_map = {"scalping": 10, "day_trading": 120, "swing": 1440}
            max_duration = max_duration_map.get(strategy_mode, 10)

            if trade.open_time:
                duration_min = (now - trade.open_time).total_seconds() / 60
                if duration_min >= max_duration:
                    price_data = prices_map.get(trade.symbol)
                    if not price_data:
                        continue
                    exit_price = price_data.get("bid") if trade.direction == models.TradeDirection.SELL.value else price_data.get("ask")
                    if exit_price:
                        closed_trade = await self.close_trade(db, trade.id, exit_price, f"max_duration_{max_duration}min")
                        closed.append(closed_trade)
        return closed

    async def close_all_open_positions(self, db: AsyncSession, close_reason: str = "eod") -> List[models.Trade]:
        """Close ALL open positions immediately (used for EOD / weekend closure)."""
        result = await db.execute(
            select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_trades = result.scalars().all()
        if not open_trades:
            return []
        closed = []
        client = self._get_client()

        # Batch fetch all prices in parallel
        symbols = [t.symbol for t in open_trades]
        prices_map = await self._fetch_prices_batch(client, symbols)

        for trade in open_trades:
            price_data = prices_map.get(trade.symbol)
            if not price_data:
                continue
            exit_price = price_data.get("bid") if trade.direction == models.TradeDirection.SELL.value else price_data.get("ask")
            if exit_price:
                closed_trade = await self.close_trade(db, trade.id, exit_price, close_reason)
                closed.append(closed_trade)
        return closed

    async def check_trailing_stops(self, db: AsyncSession):
        """Update trailing stops and close if hit."""
        from app.services.settings_service import get_setting_bool
        trailing_enabled = await get_setting_bool(db, "trailing_stop_enabled")
        if not trailing_enabled:
            return []

        result = await db.execute(
            select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_trades = result.scalars().all()
        if not open_trades:
            return []

        # Filter to trades with trailing stops configured
        trailing_trades = [t for t in open_trades if t.trailing_stop_distance]
        if not trailing_trades:
            return []

        client = self._get_client()
        closed = []
        updated = []

        # Batch fetch all prices in parallel
        symbols = [t.symbol for t in trailing_trades]
        prices_map = await self._fetch_prices_batch(client, symbols)

        for trade in trailing_trades:
            price_data = prices_map.get(trade.symbol)
            if not price_data:
                continue
            price = price_data.get("ask") if trade.direction == models.TradeDirection.BUY.value else price_data.get("bid")
            if not price:
                continue

            entry = trade.entry_price
            sl = trade.stop_loss
            dist = trade.trailing_stop_distance

            if trade.direction == models.TradeDirection.BUY.value:
                # Track highest price seen
                if trade.highest_price_seen is None or price > trade.highest_price_seen:
                    trade.highest_price_seen = price
                highest = trade.highest_price_seen or entry
                # Activate trailing once price moves dist above entry
                activation = entry + dist
                if price >= activation and not trade.trailing_stop_active:
                    trade.trailing_stop_active = True
                    # Move SL to breakeven (or better)
                    new_sl = max(sl, entry) if sl else entry
                    trade.stop_loss = round(new_sl, 5)
                    updated.append(trade)
                elif trade.trailing_stop_active:
                    new_sl = highest - dist
                    if new_sl > trade.stop_loss:
                        trade.stop_loss = round(new_sl, 5)
                        updated.append(trade)
                # Check if price hit trailing stop
                if trade.trailing_stop_active and price <= trade.stop_loss:
                    closed_trade = await self.close_trade(db, trade.id, price, "trailing_stop")
                    closed.append(closed_trade)
                    continue

            else:  # SELL
                if trade.lowest_price_seen is None or price < trade.lowest_price_seen:
                    trade.lowest_price_seen = price
                lowest = trade.lowest_price_seen or entry
                activation = entry - dist
                if price <= activation and not trade.trailing_stop_active:
                    trade.trailing_stop_active = True
                    new_sl = min(sl, entry) if sl else entry
                    trade.stop_loss = round(new_sl, 5)
                    updated.append(trade)
                elif trade.trailing_stop_active:
                    new_sl = lowest + dist
                    if new_sl < trade.stop_loss:
                        trade.stop_loss = round(new_sl, 5)
                        updated.append(trade)
                if trade.trailing_stop_active and price >= trade.stop_loss:
                    closed_trade = await self.close_trade(db, trade.id, price, "trailing_stop")
                    closed.append(closed_trade)
                    continue

        await db.commit()
        return closed

    async def check_partial_profits(self, db: AsyncSession):
        """Close 50% of position at 1R profit and move SL to breakeven."""
        from app.services.settings_service import get_setting_bool, get_setting_float
        partial_enabled = await get_setting_bool(db, "partial_profit_enabled")
        if not partial_enabled:
            return []

        partial_pct = await get_setting_float(db, "partial_profit_pct") / 100.0
        r_multiple = await get_setting_float(db, "partial_profit_r_multiple")

        result = await db.execute(
            select(models.Trade).where(
                models.Trade.status == models.TradeStatus.OPEN,
                models.Trade.closed_portion == 0.0,
            )
        )
        open_trades = result.scalars().all()
        if not open_trades:
            return []
        partials = []
        client = self._get_client()

        # Batch fetch all prices in parallel
        symbols = [t.symbol for t in open_trades]
        prices_map = await self._fetch_prices_batch(client, symbols)

        for trade in open_trades:
            if not trade.entry_price or not trade.stop_loss:
                continue
            sl_dist = abs(trade.entry_price - trade.stop_loss)
            if sl_dist == 0:
                continue
            target_price = trade.entry_price + (sl_dist * r_multiple) if trade.direction == models.TradeDirection.BUY.value else trade.entry_price - (sl_dist * r_multiple)

            price_data = prices_map.get(trade.symbol)
            if not price_data:
                continue
            price = price_data.get("ask") if trade.direction == models.TradeDirection.BUY.value else price_data.get("bid")
            if not price:
                continue

            # Check if 1R target reached
            if trade.direction == models.TradeDirection.BUY.value:
                reached = price >= target_price
            else:
                reached = price <= target_price

            if reached:
                # Close partial_pct of position
                close_size = trade.position_size * partial_pct
                portion_pnl = (price - trade.entry_price) * close_size * 100000 if trade.direction == models.TradeDirection.BUY.value else (trade.entry_price - price) * close_size * 100000

                trade.partial_pnl = (trade.partial_pnl or 0) + portion_pnl
                trade.closed_portion = (trade.closed_portion or 0) + partial_pct
                trade.position_size = trade.position_size - close_size

                # Move SL to breakeven
                trade.stop_loss = round(trade.entry_price, 5)
                trade.rationale = (trade.rationale or "") + f" | Partial close {int(partial_pct*100)}% at {price:.5f} (1R). SL moved to BE."
                partials.append(trade)

        await db.commit()
        return partials

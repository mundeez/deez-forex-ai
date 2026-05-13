from datetime import datetime
from typing import Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app import models, schemas
from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
from app.config import get_settings

settings = get_settings()


class ExecutionService:
    def __init__(self):
        self.metaapi = MetaApiClient()
        self.mt5_zmq = MT5ZMQClient()

    def _get_client(self, provider: schemas.DataProvider = None):
        provider = provider or settings.DATA_PROVIDER
        if provider == schemas.DataProvider.mt5_zmq:
            return self.mt5_zmq
        return self.metaapi

    async def execute_trade(self, db: AsyncSession, trade_in: schemas.TradeCreate) -> models.Trade:
        now = datetime.utcnow()
        client = self._get_client(trade_in.provider)
        trade = models.Trade(
            symbol=trade_in.symbol,
            direction=trade_in.direction.value,
            status=models.TradeStatus.OPEN,
            mode=trade_in.mode.value,
            entry_price=trade_in.entry_price,
            stop_loss=trade_in.stop_loss,
            take_profit=trade_in.take_profit,
            position_size=trade_in.position_size,
            risk_pct=trade_in.risk_pct,
            ai_decision_id=trade_in.ai_decision_id,
            open_time=now,
            rationale=trade_in.rationale,
            provider=trade_in.provider.value,
        )

        is_live = trade_in.mode == schemas.TradeMode.live
        is_metaapi = trade_in.provider == schemas.DataProvider.metaapi
        has_meta_token = bool(settings.META_API_TOKEN)

        if is_live and (has_meta_token if is_metaapi else True):
            order = {
                "symbol": trade_in.symbol,
                "actionType": "ORDER_TYPE_BUY" if trade_in.direction == schemas.TradeDirection.buy else "ORDER_TYPE_SELL",
                "volume": trade_in.position_size or 0.01,
                "stopLoss": trade_in.stop_loss,
                "takeProfit": trade_in.take_profit,
            }
            resp = await client.place_trade(order)
            trade.meta_order_id = resp.get("id")
        else:
            trade.mode = models.TradeMode.PAPER
            trade.meta_order_id = f"paper-{now.strftime('%Y%m%d%H%M%S')}-{trade_in.symbol}"

        db.add(trade)
        await db.commit()
        await db.refresh(trade)
        return trade

    async def close_trade(self, db: AsyncSession, trade_id: int, exit_price: float) -> models.Trade:
        result = await db.execute(select(models.Trade).where(models.Trade.id == trade_id))
        trade: Optional[models.Trade] = result.scalar_one_or_none()
        if not trade:
            raise ValueError(f"Trade {trade_id} not found")

        trade.exit_price = exit_price
        trade.status = models.TradeStatus.CLOSED
        trade.close_time = datetime.utcnow()

        if trade.direction == models.TradeDirection.BUY.value:
            trade.pnl = (exit_price - trade.entry_price) * (trade.position_size or 0.01) * 100000
            trade.pnl_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100 if trade.entry_price else 0
        else:
            trade.pnl = (trade.entry_price - exit_price) * (trade.position_size or 0.01) * 100000
            trade.pnl_pct = ((trade.entry_price - exit_price) / trade.entry_price) * 100 if trade.entry_price else 0

        if trade.meta_order_id and trade.mode == models.TradeMode.LIVE.value:
            client = self._get_client(schemas.DataProvider(trade.provider))
            await client.close_position(trade.meta_order_id)

        await db.commit()
        await db.refresh(trade)
        return trade

    async def check_and_close_positions(self, db: AsyncSession):
        # Use default configured provider for SL/TP monitoring
        client = self._get_client()
        price_data = await client.get_current_price(settings.DEFAULT_PAIR)
        current_bid = price_data.get("bid")
        current_ask = price_data.get("ask")
        if not current_bid or not current_ask:
            return []

        result = await db.execute(
            select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN)
        )
        open_trades = result.scalars().all()
        closed = []
        for trade in open_trades:
            # Get symbol-specific price for each trade
            try:
                sym_price = await client.get_current_price(trade.symbol)
                sym_bid = sym_price.get("bid", current_bid)
                sym_ask = sym_price.get("ask", current_ask)
            except Exception:
                sym_bid = current_bid
                sym_ask = current_ask

            price = sym_ask if trade.direction == models.TradeDirection.BUY.value else sym_bid
            if (trade.direction == models.TradeDirection.BUY.value and price <= trade.stop_loss) or \
               (trade.direction == models.TradeDirection.SELL.value and price >= trade.stop_loss):
                closed_trade = await self.close_trade(db, trade.id, price)
                closed.append(closed_trade)
            elif (trade.direction == models.TradeDirection.BUY.value and price >= trade.take_profit) or \
                 (trade.direction == models.TradeDirection.SELL.value and price <= trade.take_profit):
                closed_trade = await self.close_trade(db, trade.id, price)
                closed.append(closed_trade)
        return closed

import json
import logging
import redis.asyncio as aioredis
from app.config import get_settings
from app.utils.time import utc_now

settings = get_settings()
logger = logging.getLogger("app.services.websocket")

# Channel names for Redis pub/sub
CHANNEL_PRICES = "ws:prices"
CHANNEL_TRADES = "ws:trades"
CHANNEL_AI_DECISIONS = "ws:ai_decisions"
CHANNEL_SETTINGS = "ws:settings"


async def _get_redis():
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def broadcast_via_redis(channel: str, message: dict):
    try:
        redis = await _get_redis()
        await redis.publish(channel, json.dumps(message))
        await redis.close()
    except Exception:
        logger.warning("Failed to broadcast via Redis", exc_info=True)


async def broadcast_price_tick(symbol: str, bid: float, ask: float, timestamp: str = None):
    from datetime import datetime
    await broadcast_via_redis(CHANNEL_PRICES, {
        "type": "price_tick",
        "topic": "prices",
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "timestamp": timestamp or utc_now().isoformat(),
    })


async def broadcast_trade_event(event_type: str, trade_data: dict):
    await broadcast_via_redis(CHANNEL_TRADES, {
        "type": "trade_event",
        "topic": "trades",
        "event": event_type,
        "data": trade_data,
    })


async def broadcast_ai_decision(decision_data: dict):
    await broadcast_via_redis(CHANNEL_AI_DECISIONS, {
        "type": "ai_decision",
        "topic": "ai_decisions",
        "data": decision_data,
    })


async def broadcast_settings_change(settings_data: dict):
    await broadcast_via_redis(CHANNEL_SETTINGS, {
        "type": "settings_change",
        "topic": "settings",
        "data": settings_data,
    })

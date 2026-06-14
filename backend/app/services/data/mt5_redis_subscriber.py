"""
Redis pub/sub subscriber for real-time MT5 ticks.

Subscribes to Redis channel pattern "mt5:ticks:*" and calls the
on_tick callback for each incoming tick message.

This replaces MT5ZMQSubscriber when DATA_PROVIDER=mt5_rpyc,
using Redis as the streaming backbone.
"""
import asyncio
import json
import logging
from typing import Optional, Callable

import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.data.mt5_redis_sub")


class MT5RedisTickSubscriber:
    """Async Redis subscriber that receives real-time ticks from MT5."""

    def __init__(
        self,
        redis_url: str = None,
        channel_pattern: str = "mt5:ticks:*",
        on_tick: Optional[Callable] = None,
    ):
        self.redis_url = redis_url or settings.REDIS_URL
        self.channel_pattern = channel_pattern
        self.on_tick = on_tick
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(self.channel_pattern)
        self._task = asyncio.create_task(self._loop())
        logger.info("MT5RedisTickSubscriber started (pattern: %s)", self.channel_pattern)

    async def _loop(self):
        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break
                if message["type"] not in ("pmessage", "message"):
                    continue
                try:
                    data = json.loads(message["data"])
                    if self.on_tick:
                        asyncio.create_task(self.on_tick(data))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Invalid tick message: %s — %s", message, e)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Error in Redis subscriber loop", exc_info=True)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.punsubscribe(self.channel_pattern)
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info("MT5RedisTickSubscriber stopped")

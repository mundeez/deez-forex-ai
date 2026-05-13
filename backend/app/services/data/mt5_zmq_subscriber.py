import asyncio
import json
import zmq.asyncio
from typing import Optional, Callable
from app.config import get_settings

settings = get_settings()


class MT5ZMQSubscriber:
    """Async SUB socket that receives real-time ticks from MT5 OnTick()."""

    def __init__(
        self,
        host: str = None,
        pub_port: int = None,
        on_tick: Optional[Callable] = None,
    ):
        self.host = host or settings.MT5_ZMQ_HOST
        self.pub_port = pub_port or settings.MT5_ZMQ_PUB_PORT
        self.pub_addr = f"tcp://{self.host}:{self.pub_port}"
        self.on_tick = on_tick
        self._context: Optional[zmq.asyncio.Context] = None
        self._socket: Optional[zmq.asyncio.Socket] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._context = zmq.asyncio.Context()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.setsockopt(zmq.RCVTIMEO, 1000)
        self._socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self._socket.connect(self.pub_addr)
        self._task = asyncio.create_task(self._loop())

    async def _loop(self):
        while self._running:
            try:
                raw = await self._socket.recv_string()
                msg = json.loads(raw)
                if self.on_tick:
                    asyncio.create_task(self.on_tick(msg))
            except zmq.Again:
                await asyncio.sleep(0.01)
            except Exception:
                await asyncio.sleep(0.5)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._socket and not self._socket.closed:
            self._socket.close()
        if self._context:
            self._context.term()

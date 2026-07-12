"""
Async RPyC client that talks to the MT5 container's custom MT5Service.

This client wraps synchronous rpyc calls in asyncio.to_thread() so it
plays nicely with FastAPI's async event loop.

Interface matches MT5ZMQClient exactly so it can be dropped in as a
data provider without changing caller code.
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional

import rpyc
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.data.mt5_rpyc")


class MT5RPyCClient:
    """Async RPyC client for MT5Service."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
    ):
        self.host = host or settings.MT5_RPYC_HOST
        self.port = port or settings.MT5_RPYC_PORT
        self._conn: Optional[rpyc.Connection] = None
        self._lock = asyncio.Lock()

    def _connect(self) -> rpyc.Connection:
        """Synchronous connection helper."""
        logger.debug("RPyC connecting to %s:%d", self.host, self.port)
        conn = rpyc.connect(
            self.host,
            self.port,
            config={"sync_request_timeout": 15, "allow_public_attrs": True},
        )
        logger.debug("RPyC connected")
        return conn

    async def _get_root(self):
        """Get (or reconnect) the RPyC root object. Thread-safe + asyncio-safe."""
        async with self._lock:
            if self._conn is None or self._conn.closed:
                try:
                    self._conn = await asyncio.to_thread(self._connect)
                except Exception as e:
                    logger.error("RPyC connection failed: %s", e)
                    raise ConnectionError(f"Cannot connect to MT5 RPyC service at {self.host}:{self.port}: {e}")
            return self._conn.root

    async def _call(self, method: str, *args, **kwargs) -> Any:
        """Call an exposed method on the remote MT5Service."""
        root = await self._get_root()
        exposed_method = getattr(root, f"exposed_{method}", None)
        if exposed_method is None:
            raise AttributeError(f"MT5Service does not expose method: {method}")
        return await asyncio.wait_for(
            asyncio.to_thread(exposed_method, *args, **kwargs),
            timeout=10,
        )

    async def get_current_price(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        resp = await self._call("get_price", symbol)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return {
            "symbol": symbol,
            "bid": resp.get("bid"),
            "ask": resp.get("ask"),
            "timestamp": resp.get("timestamp"),
        }

    async def get_historical_candles(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "1h",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        resp = await self._call("get_candles", symbol, timeframe, limit)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        # Convert RPyC netrefs to plain Python dicts to avoid network round-trips
        # on every attribute access during pandas operations
        raw_candles = resp.get("candles", [])
        return [
            {
                "timestamp": int(c["timestamp"]),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": int(c["volume"]),
            }
            for c in raw_candles
        ]

    async def place_trade(self, order: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._call("place_trade", order)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return {
            "id": resp.get("ticket"),
            "status": "ACCEPTED" if resp.get("result") == "done" else "REJECTED",
            "details": resp,
        }

    async def close_position(self, position_id: str) -> Dict[str, Any]:
        resp = await self._call("close_position", int(position_id))
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return {
            "id": position_id,
            "status": "CLOSED" if resp.get("result") == "done" else "FAILED",
            "details": resp,
        }

    async def get_account_info(self) -> Dict[str, Any]:
        resp = await self._call("get_account")
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return {
            "balance": resp.get("balance"),
            "equity": resp.get("equity"),
            "margin": resp.get("margin"),
            "free_margin": resp.get("free_margin"),
            "currency": resp.get("currency"),
            "leverage": resp.get("leverage"),
        }

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        resp = await self._call("get_positions")
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return [dict(p) for p in resp.get("positions", [])]

    async def get_pending_orders(self) -> List[Dict[str, Any]]:
        resp = await self._call("get_orders")
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return [dict(o) for o in resp.get("orders", [])]

    async def modify_position(
        self, ticket: int, sl: float = None, tp: float = None
    ) -> Dict[str, Any]:
        resp = await self._call("modify_position", ticket, sl, tp)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp

    async def get_history_deals(
        self, date_from: str = "", date_to: str = "", group: str = ""
    ) -> List[Dict[str, Any]]:
        resp = await self._call("get_history_deals", date_from, date_to, group)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return [dict(d) for d in resp.get("deals", [])]

    async def get_history_orders(
        self, date_from: str = "", date_to: str = ""
    ) -> List[Dict[str, Any]]:
        resp = await self._call("get_history_orders", date_from, date_to)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return [dict(o) for o in resp.get("orders", [])]

    async def login(self, login: int, password: str, server: str, timeout: int = 60000) -> Dict[str, Any]:
        resp = await self._call("login", login, password, server, timeout)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp

    async def get_terminal_info(self) -> Dict[str, Any]:
        resp = await self._call("terminal_info")
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp

    async def get_symbols(self, group: str = "") -> List[Dict[str, Any]]:
        resp = await self._call("get_symbols", group)
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp.get("symbols", [])

    async def close(self):
        async with self._lock:
            if self._conn and not self._conn.closed:
                await asyncio.to_thread(self._conn.close)
            self._conn = None

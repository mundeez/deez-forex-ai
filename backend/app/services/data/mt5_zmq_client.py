import json
import zmq.asyncio
from typing import Dict, List, Any, Optional
from app.config import get_settings

settings = get_settings()


class MT5ZMQClient:
    """Async ZeroMQ client that talks directly to an MT5 terminal or container."""

    def __init__(
        self,
        host: str = None,
        req_port: int = None,
    ):
        self.host = host or settings.MT5_ZMQ_HOST
        self.req_port = req_port or settings.MT5_ZMQ_REQ_PORT
        self.req_addr = f"tcp://{self.host}:{self.req_port}"
        self._context: Optional[zmq.asyncio.Context] = None
        self._socket: Optional[zmq.asyncio.Socket] = None

    async def _ensure_socket(self):
        if self._socket is None or self._socket.closed:
            self._context = zmq.asyncio.Context()
            self._socket = self._context.socket(zmq.REQ)
            # 12s timeout — accommodates mt5.initialize(5s) + network overhead + retries
            self._socket.setsockopt(zmq.RCVTIMEO, 12000)
            self._socket.setsockopt(zmq.SNDTIMEO, 5000)
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.connect(self.req_addr)

    async def _send(self, payload: dict, retries: int = 1) -> dict:
        last_error = None
        for attempt in range(retries + 1):
            await self._ensure_socket()
            try:
                await self._socket.send_string(json.dumps(payload))
                raw = await self._socket.recv_string()
                return json.loads(raw)
            except zmq.Again:
                last_error = TimeoutError(f"MT5 ZMQ timeout on {self.req_addr} (attempt {attempt + 1})")
            except Exception as e:
                last_error = e
            # Recreate socket on error to avoid REQ/REP deadlock
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        raise last_error

    async def get_current_price(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        resp = await self._send({"action": "GET_PRICE", "symbol": symbol})
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        bid = resp.get("bid")
        ask = resp.get("ask")
        # Sanity check: reject obviously corrupt prices
        if bid is None or ask is None:
            raise RuntimeError(f"MT5 returned null price for {symbol}")
        # Spread check: reject if spread > 5% of price (impossible for forex)
        if bid > 0 and (ask - bid) / bid > 0.05:
            raise RuntimeError(f"MT5 returned insane spread for {symbol}: bid={bid} ask={ask}")
        # Range check: reject if price is outside plausible forex range
        from app.services.instruments import pip_size
        pip = pip_size(symbol)
        # For major forex pairs, price should be roughly 0.5 - 300
        # Gold can be 1000-3000, JPY pairs ~100-200
        mid = (bid + ask) / 2.0
        if symbol == "XAUUSD":
            if not (500 <= mid <= 5000):
                raise RuntimeError(f"MT5 returned out-of-range gold price: {mid}")
        elif "JPY" in symbol:
            if not (50 <= mid <= 400):
                raise RuntimeError(f"MT5 returned out-of-range JPY price: {mid}")
        else:
            if not (0.3 <= mid <= 50):
                raise RuntimeError(f"MT5 returned out-of-range price for {symbol}: {mid}")
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "timestamp": resp.get("timestamp"),
        }

    async def get_historical_candles(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "1h",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        resp = await self._send(
            {"action": "GET_CANDLES", "symbol": symbol, "timeframe": timeframe, "limit": limit}
        )
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp.get("candles", [])

    async def place_trade(self, order: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self._send({"action": "TRADE", **order})
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return {
            "id": resp.get("ticket"),
            "status": "ACCEPTED" if resp.get("result") == "done" else "REJECTED",
            "details": resp,
        }

    async def close_position(self, position_id: str) -> Dict[str, Any]:
        resp = await self._send({"action": "CLOSE", "ticket": position_id})
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return {
            "id": position_id,
            "status": "CLOSED" if resp.get("result") == "done" else "FAILED",
            "details": resp,
        }

    async def get_account_info(self) -> Dict[str, Any]:
        resp = await self._send({"action": "GET_ACCOUNT"})
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
        resp = await self._send({"action": "GET_POSITIONS"})
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp.get("positions", [])

    async def get_ticks(
        self,
        symbol: str = "EURUSD",
        from_ms: int = 0,
        to_ms: int = 0,
    ) -> List[Dict[str, Any]]:
        """Fetch raw ticks from MT5 ZMQ bridge."""
        resp = await self._send({
            "action": "GET_TICKS",
            "symbol": symbol,
            "from_ms": from_ms,
            "to_ms": to_ms,
        })
        if resp.get("error"):
            raise RuntimeError(resp["error"])
        return resp.get("ticks", [])

    async def close(self):
        if self._socket and not self._socket.closed:
            self._socket.close()
        if self._context:
            self._context.term()

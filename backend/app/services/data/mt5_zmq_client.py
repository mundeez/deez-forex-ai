import json
import zmq.asyncio
from typing import Dict, List, Any, Optional
from app.config import get_settings

settings = get_settings()


class MT5ZMQClient:
    """Async ZeroMQ client that talks directly to a desktop MT5 terminal."""

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
            self._socket.setsockopt(zmq.RCVTIMEO, 5000)
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.connect(self.req_addr)

    async def _send(self, payload: dict) -> dict:
        await self._ensure_socket()
        try:
            await self._socket.send_string(json.dumps(payload))
            raw = await self._socket.recv_string()
            return json.loads(raw)
        except zmq.Again:
            raise TimeoutError(f"MT5 ZMQ timeout on {self.req_addr}")
        except Exception as e:
            # Recreate socket on error to avoid REQ/REP deadlock
            self._socket.close()
            self._socket = None
            raise e

    async def get_current_price(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        resp = await self._send({"action": "GET_PRICE", "symbol": symbol})
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

    async def close(self):
        if self._socket and not self._socket.closed:
            self._socket.close()
        if self._context:
            self._context.term()

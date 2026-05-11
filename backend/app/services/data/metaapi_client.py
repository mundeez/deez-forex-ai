import os
import httpx
from typing import Dict, List, Any, Optional
from app.config import get_settings

settings = get_settings()

META_API_BASE = "https://metastats-api-v1.new-york.agiliumtrade.ai"
META_API_STREAM = "https://metastats-api-v1.new-york.agiliumtrade.ai"


class MetaApiClient:
    def __init__(self):
        self.token = settings.META_API_TOKEN
        self.account_id = settings.META_API_ACCOUNT_ID
        self.headers = {"auth-token": self.token} if self.token else {}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def get_current_price(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        if not self.token:
            return self._mock_price(symbol)
        url = f"{META_API_BASE}/users/current/accounts/{self.account_id}/symbols/{symbol}/current-price"
        resp = await self._client.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    async def get_historical_candles(
        self,
        symbol: str = "EURUSD",
        timeframe: str = "1h",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        if not self.token:
            return self._mock_candles(symbol, timeframe, limit)
        url = f"{META_API_BASE}/users/current/accounts/{self.account_id}/historical-market-data/symbols/{symbol}/timeframes/{timeframe}/candles"
        params = {"limit": limit}
        resp = await self._client.get(url, headers=self.headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("candles", [])

    async def place_trade(self, order: Dict[str, Any]) -> Dict[str, Any]:
        if not self.token:
            return {"id": "paper-" + os.urandom(4).hex(), "status": "ACCEPTED"}
        url = f"{META_API_BASE}/users/current/accounts/{self.account_id}/trade"
        resp = await self._client.post(url, headers=self.headers, json=order)
        resp.raise_for_status()
        return resp.json()

    async def close_position(self, position_id: str) -> Dict[str, Any]:
        if not self.token:
            return {"id": position_id, "status": "CLOSED"}
        url = f"{META_API_BASE}/users/current/accounts/{self.account_id}/positions/{position_id}/close"
        resp = await self._client.post(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def _mock_price(self, symbol: str) -> Dict[str, Any]:
        import random, time
        base = 1.0850
        return {
            "symbol": symbol,
            "bid": round(base - random.uniform(0.0001, 0.0010), 5),
            "ask": round(base + random.uniform(0.0001, 0.0010), 5),
            "timestamp": int(time.time() * 1000),
        }

    def _mock_candles(self, symbol: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
        import random, time
        import pandas as pd
        base = 1.0850
        candles = []
        now = pd.Timestamp.now(tz="UTC")
        freq_map = {
            "1m": pd.Timedelta(minutes=1),
            "5m": pd.Timedelta(minutes=5),
            "15m": pd.Timedelta(minutes=15),
            "1h": pd.Timedelta(hours=1),
            "4h": pd.Timedelta(hours=4),
            "1d": pd.Timedelta(days=1),
        }
        delta = freq_map.get(timeframe, pd.Timedelta(hours=1))
        for i in range(limit, 0, -1):
            ts = now - (delta * i)
            o = round(base + random.uniform(-0.005, 0.005), 5)
            c = round(o + random.uniform(-0.003, 0.003), 5)
            h = round(max(o, c) + random.uniform(0, 0.002), 5)
            l = round(min(o, c) - random.uniform(0, 0.002), 5)
            candles.append({
                "timestamp": ts.isoformat(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": int(random.uniform(100, 5000)),
            })
        return candles

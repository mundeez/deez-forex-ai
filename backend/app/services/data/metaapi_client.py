import os
import random
import time
import httpx
import redis.asyncio as aioredis
from typing import Dict, List, Any, Optional
from app.config import get_settings
from app.services import instruments

settings = get_settings()

META_API_BASE = "https://metastats-api-v1.new-york.agiliumtrade.ai"
META_API_STREAM = "https://metastats-api-v1.new-york.agiliumtrade.ai"

# How far the mock mid-price may drift from its anchor before mean-reversion clamps it.
_MOCK_BAND = 0.10  # +/-10%
_MOCK_REVERSION = 0.02  # pull back toward the anchor each step


class MetaApiClient:
    def __init__(self):
        self.token = settings.META_API_TOKEN
        self.account_id = settings.META_API_ACCOUNT_ID
        self.headers = {"auth-token": self.token} if self.token else {}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def get_current_price(self, symbol: str = "EURUSD") -> Dict[str, Any]:
        if not self.token:
            return await self._mock_price(symbol)
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
            mid = await self._walk_mid(symbol, advance=False)
            return self._mock_candles(symbol, timeframe, limit, mid)
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

    # ------------------------------------------------------------------ mock --
    async def _walk_mid(self, symbol: str, advance: bool = True) -> float:
        """Return the current mock mid-price for a symbol.

        Uses a Redis-persisted mean-reverting random walk so consecutive ticks
        and candles connect into a realistic price path (instead of the old
        fixed 1.0850 oscillator). ``advance=False`` peeks without moving the walk
        (used when generating historical candles so they don't perturb the live
        tick path).
        """
        m = instruments.meta(symbol)
        base = m["base"]
        key = f"mock:mid:{symbol}"
        try:
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            cur = await r.get(key)
            mid = float(cur) if cur else base
            if advance:
                mid += random.gauss(0, m["step"]) - _MOCK_REVERSION * (mid - base)
                lo, hi = base * (1 - _MOCK_BAND), base * (1 + _MOCK_BAND)
                mid = max(lo, min(hi, mid))
                await r.set(key, f"{mid:.6f}", ex=86400)
            await r.close()
            return mid
        except Exception:
            # Redis unavailable — fall back to a stateless jittered price.
            return base + random.gauss(0, m["step"])

    async def _mock_price(self, symbol: str) -> Dict[str, Any]:
        m = instruments.meta(symbol)
        mid = await self._walk_mid(symbol, advance=True)
        dec = instruments.price_decimals(symbol)
        half = m["spread"] / 2.0
        return {
            "symbol": symbol,
            "bid": round(mid - half, dec),
            "ask": round(mid + half, dec),
            "timestamp": int(time.time() * 1000),
        }

    def _mock_candles(self, symbol: str, timeframe: str, limit: int, mid: Optional[float] = None) -> List[Dict[str, Any]]:
        import pandas as pd
        m = instruments.meta(symbol)
        base = m["base"]
        dec = instruments.price_decimals(symbol)
        mid = base if mid is None else mid
        candle_step = m["step"] * 2.0  # per-candle move > per-tick move

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

        # Build a mean-reverting close series of length limit+1 that ENDS at `mid`.
        closes = [mid]
        for _ in range(limit):
            prev = closes[0] - random.gauss(0, candle_step) + _MOCK_REVERSION * (closes[0] - base)
            lo, hi = base * (1 - _MOCK_BAND), base * (1 + _MOCK_BAND)
            closes.insert(0, max(lo, min(hi, prev)))

        candles = []
        for i in range(limit):
            o = closes[i]
            c = closes[i + 1]
            wick = abs(random.gauss(0, candle_step * 0.5))
            h = max(o, c) + wick
            l = min(o, c) - wick
            ts = now - (delta * (limit - i))
            candles.append({
                "timestamp": ts.isoformat(),
                "open": round(o, dec),
                "high": round(h, dec),
                "low": round(l, dec),
                "close": round(c, dec),
                "volume": int(random.uniform(100, 5000)),
            })
        return candles

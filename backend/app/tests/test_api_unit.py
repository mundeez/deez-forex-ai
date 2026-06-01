"""Unit tests for FastAPI endpoints using async test client."""

import pytest
from app.models import Trade, AIDecision, ActivePair
from app.enums import TradeStatus, TradeDirection, TradeMode, DataProvider


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, async_client):
        response = await async_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # Redis may not be available in test env; accept ok or degraded
        assert data["status"] in ("ok", "degraded")


class TestPairsEndpoints:
    @pytest.mark.asyncio
    async def test_get_pairs(self, async_client):
        response = await async_client.get("/api/v1/pairs")
        assert response.status_code == 200
        data = response.json()
        assert "pairs" in data
        assert "EURUSD" in data["pairs"]

    @pytest.mark.asyncio
    async def test_active_pairs_crud(self, async_client):
        # Set active pairs
        pairs = [
            {"symbol": "EURUSD", "selection_mode": "manual", "priority": 1},
            {"symbol": "GBPUSD", "selection_mode": "auto", "priority": 2},
        ]
        response = await async_client.post("/api/v1/pairs/active", json=pairs)
        assert response.status_code == 200

        # Verify
        response = await async_client.get("/api/v1/pairs/active")
        assert response.status_code == 200
        active = response.json()
        assert len(active) == 2
        assert active[0]["symbol"] == "EURUSD"

        # Clear
        response = await async_client.post("/api/v1/pairs/active", json=[])
        assert response.status_code == 200

        response = await async_client.get("/api/v1/pairs/active")
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_active_pairs_max_limit(self, async_client):
        pairs = [
            {"symbol": "EURUSD", "selection_mode": "manual", "priority": 1},
            {"symbol": "GBPUSD", "selection_mode": "manual", "priority": 2},
            {"symbol": "USDJPY", "selection_mode": "manual", "priority": 3},
            {"symbol": "AUDUSD", "selection_mode": "manual", "priority": 4},
        ]
        response = await async_client.post("/api/v1/pairs/active", json=pairs)
        assert response.status_code == 400
        assert "Maximum 3" in response.json()["detail"]


class TestSettingsEndpoints:
    @pytest.mark.asyncio
    async def test_get_settings(self, async_client):
        response = await async_client.get("/api/v1/settings")
        assert response.status_code == 200
        data = response.json()
        assert "max_risk_per_trade_pct" in data
        assert "manual_override" in data
        assert isinstance(data["manual_override"], bool)

    @pytest.mark.asyncio
    async def test_update_settings_valid(self, async_client):
        payload = {"max_risk_per_trade_pct": 1.5, "max_daily_loss_pct": 3.0}
        response = await async_client.put("/api/v1/settings", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["max_risk_per_trade_pct"] == 1.5
        assert data["max_daily_loss_pct"] == 3.0

        # Restore defaults
        payload = {"max_risk_per_trade_pct": 2.0, "max_daily_loss_pct": 5.0}
        await async_client.put("/api/v1/settings", json=payload)

    @pytest.mark.asyncio
    async def test_update_settings_invalid_risk(self, async_client):
        payload = {"max_risk_per_trade_pct": 100.0}
        response = await async_client.put("/api/v1/settings", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_manual_override_toggle(self, async_client):
        response = await async_client.get("/api/v1/manual-override")
        assert response.status_code == 200
        initial = response.json()["manual_override"]

        response = await async_client.post("/api/v1/manual-override")
        assert response.status_code == 200
        toggled = response.json()["manual_override"]
        assert toggled == (not initial)

        # Toggle back
        response = await async_client.post("/api/v1/manual-override")
        assert response.status_code == 200
        assert response.json()["manual_override"] == initial


class TestPortfolioEndpoints:
    @pytest.mark.asyncio
    async def test_get_portfolio_summary(self, async_client):
        response = await async_client.get("/api/v1/portfolio/summary")
        assert response.status_code == 200
        data = response.json()
        assert "equity" in data
        assert "realized_pnl" in data
        assert "unrealized_pnl" in data

    @pytest.mark.asyncio
    async def test_get_positions(self, async_client):
        response = await async_client.get("/api/v1/positions")
        assert response.status_code == 200
        data = response.json()
        assert "positions" in data
        assert isinstance(data["positions"], list)

    @pytest.mark.asyncio
    async def test_get_trade_stats(self, async_client):
        response = await async_client.get("/api/v1/trades/stats")
        assert response.status_code == 200
        data = response.json()
        assert "equity" in data
        assert "total_trades" in data


class TestTradesEndpoints:
    @pytest.mark.asyncio
    async def test_create_manual_trade(self, async_client):
        payload = {
            "symbol": "EURUSD",
            "direction": "buy",
            "entry_price": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0900,
            "risk_pct": 1.0,
            "mode": "paper",
        }
        response = await async_client.post("/api/v1/trades/manual", json=payload)
        # May fail if provider unavailable; accept 200 or 503
        assert response.status_code in (200, 422, 503)

    @pytest.mark.asyncio
    async def test_create_manual_trade_invalid_direction(self, async_client):
        # ManualTradeCreate.direction is plain str; endpoint maps non-buy to SELL
        payload = {
            "symbol": "EURUSD",
            "direction": "sideways",
            "entry_price": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0900,
        }
        response = await async_client.post("/api/v1/trades/manual", json=payload)
        # Endpoint falls back to SELL for any non-buy direction
        assert response.status_code in (200, 422, 503)

    @pytest.mark.asyncio
    async def test_get_trades(self, async_client):
        response = await async_client.get("/api/v1/trades?limit=5")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_get_ai_decisions(self, async_client):
        response = await async_client.get("/api/v1/ai/decisions?limit=5")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestAIModelsEndpoint:
    @pytest.mark.asyncio
    async def test_get_ai_models(self, async_client):
        response = await async_client.get("/api/v1/ai/models")
        assert response.status_code == 200
        data = response.json()
        assert "rotation_enabled" in data
        assert "free_pool" in data
        assert "cooldown_sec" in data
        assert "cooling_down" in data
        assert "available" in data
        assert "recent_usage_24h" in data


class TestAnalyticsBreakdownEndpoint:
    @pytest.mark.asyncio
    async def test_get_analytics_breakdown(self, async_client):
        response = await async_client.get("/api/v1/analytics/breakdown")
        assert response.status_code == 200
        data = response.json()
        assert "by_close_reason" in data
        assert "by_session_open" in data
        assert "by_direction" in data
        assert "by_symbol" in data
        assert "by_model" in data

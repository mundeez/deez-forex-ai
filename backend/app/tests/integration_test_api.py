import pytest
import requests

BASE_URL = "http://127.0.0.1:8000"


def test_health():
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_get_pairs():
    response = requests.get(f"{BASE_URL}/api/v1/pairs")
    assert response.status_code == 200
    data = response.json()
    assert "pairs" in data
    assert "EURUSD" in data["pairs"]


def test_get_settings():
    response = requests.get(f"{BASE_URL}/api/v1/settings")
    assert response.status_code == 200
    data = response.json()
    assert "max_risk_per_trade_pct" in data
    assert "manual_override" in data
    assert isinstance(data["manual_override"], bool)


def test_manual_override_toggle():
    # Get current state
    response = requests.get(f"{BASE_URL}/api/v1/manual-override")
    assert response.status_code == 200
    initial = response.json()["manual_override"]

    # Toggle
    response = requests.post(f"{BASE_URL}/api/v1/manual-override")
    assert response.status_code == 200
    toggled = response.json()["manual_override"]
    assert toggled == (not initial)

    # Toggle back
    response = requests.post(f"{BASE_URL}/api/v1/manual-override")
    assert response.status_code == 200
    final = response.json()["manual_override"]
    assert final == initial


def test_update_settings():
    payload = {"max_risk_per_trade_pct": 1.5, "max_daily_loss_pct": 3.0}
    response = requests.put(f"{BASE_URL}/api/v1/settings", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["max_risk_per_trade_pct"] == 1.5
    assert data["max_daily_loss_pct"] == 3.0

    # Restore defaults
    payload = {"max_risk_per_trade_pct": 2.0, "max_daily_loss_pct": 5.0}
    requests.put(f"{BASE_URL}/api/v1/settings", json=payload)


def test_get_market_current():
    response = requests.get(f"{BASE_URL}/api/v1/market/current?symbol=EURUSD")
    assert response.status_code in (200, 503)


def test_get_market_historical():
    response = requests.get(f"{BASE_URL}/api/v1/market/historical?symbol=EURUSD&timeframe=1h&limit=10")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        data = response.json()
        assert data["symbol"] == "EURUSD"
        assert data["timeframe"] == "1h"
        assert "candles" in data


def test_get_market_summary():
    response = requests.get(f"{BASE_URL}/api/v1/market/summary?symbol=EURUSD")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        data = response.json()
        assert data["symbol"] == "EURUSD"
        assert "session_status" in data


def test_get_portfolio_summary():
    response = requests.get(f"{BASE_URL}/api/v1/portfolio/summary")
    assert response.status_code == 200
    data = response.json()
    assert "equity" in data
    assert "realized_pnl" in data
    assert "unrealized_pnl" in data


def test_get_positions():
    response = requests.get(f"{BASE_URL}/api/v1/positions")
    assert response.status_code == 200
    data = response.json()
    assert "positions" in data
    assert isinstance(data["positions"], list)


def test_get_trade_stats():
    response = requests.get(f"{BASE_URL}/api/v1/trades/stats")
    assert response.status_code == 200
    data = response.json()
    assert "equity" in data
    assert "total_trades" in data


def test_get_trades():
    response = requests.get(f"{BASE_URL}/api/v1/trades?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_get_ai_decisions():
    response = requests.get(f"{BASE_URL}/api/v1/ai/decisions?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_analysis_endpoints():
    # Technical analysis
    response = requests.get(f"{BASE_URL}/api/v1/analysis/technical?symbol=EURUSD&timeframe=1h")
    assert response.status_code in (200, 503)

    # Fundamental analysis
    response = requests.get(f"{BASE_URL}/api/v1/analysis/fundamental?symbol=EURUSD")
    assert response.status_code in (200, 503)

    # Sentiment analysis
    response = requests.get(f"{BASE_URL}/api/v1/analysis/sentiment?symbol=EURUSD")
    assert response.status_code in (200, 503)

    # Full/Summary analysis
    response = requests.get(f"{BASE_URL}/api/v1/analysis/summary?symbol=EURUSD")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        data = response.json()
        assert "combined_signal" in data


def test_active_pairs_crud():
    # Get active pairs
    response = requests.get(f"{BASE_URL}/api/v1/pairs/active")
    assert response.status_code == 200

    # Set active pairs
    pairs = [
        {"symbol": "EURUSD", "selection_mode": "manual", "priority": 1},
        {"symbol": "GBPUSD", "selection_mode": "auto", "priority": 2},
    ]
    response = requests.post(f"{BASE_URL}/api/v1/pairs/active", json=pairs)
    assert response.status_code == 200
    data = response.json()
    assert "detail" in data

    # Verify
    response = requests.get(f"{BASE_URL}/api/v1/pairs/active")
    assert response.status_code == 200
    active = response.json()
    assert len(active) == 2

    # Clear pairs
    response = requests.post(f"{BASE_URL}/api/v1/pairs/active", json=[])
    assert response.status_code == 200


def test_active_pairs_max_limit():
    pairs = [
        {"symbol": "EURUSD", "selection_mode": "manual", "priority": 1},
        {"symbol": "GBPUSD", "selection_mode": "manual", "priority": 2},
        {"symbol": "USDJPY", "selection_mode": "manual", "priority": 3},
        {"symbol": "AUDUSD", "selection_mode": "manual", "priority": 4},
    ]
    response = requests.post(f"{BASE_URL}/api/v1/pairs/active", json=pairs)
    assert response.status_code == 400
    assert "Maximum 3" in response.json()["detail"]

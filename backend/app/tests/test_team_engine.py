"""Tests for the v2 AI Trading Team engine."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ai.team.analyst import DomainAnalyst
from app.ai.team.lead import LeadStrategist
from app.ai.team.verifier import Verifier
from app.ai.team.orchestrator import TeamDecisionEngine
from app.ai.team.daily_bias import DailyBiasEngine


@pytest.fixture
def sample_analysis():
    return {
        "symbol": "EURUSD",
        "technical": {
            "timeframes": {
                "5m": {
                    "signal": "bullish",
                    "confidence": 0.75,
                    "indicators": {"rsi_14": 58, "ema_9": 1.0850, "ema_21": 1.0845, "adx_14": 28, "atr_14": 0.00035},
                    "bb_squeeze": False,
                }
            },
            "overall_signal": "bullish",
        },
        "fundamental": {"direction_bias": "bullish", "event_risk": "low", "events": [], "interest_rate_spread": 1.5},
        "sentiment": {"overall_sentiment": "bullish", "sentiment_score": 0.65},
    }


@pytest.mark.asyncio
async def test_domain_analyst_output_schema(sample_analysis):
    """Analyst should return the Gemini-doc aligned schema."""
    analyst = DomainAnalyst("technical", model="openai/gpt-oss-120b:free")
    with patch.object(analyst.client, "_post_with_failover", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = (
            {"choices": [{"message": {"content": '{"bias": "BULLISH", "confidence_score": 0.82, "reasoning_short": "RSI rising", "risk_warning": "NFP in 30m"}'}}]},
            "openai/gpt-oss-120b:free",
        )
        result = await analyst.analyze(sample_analysis)

    assert result["bias"] == "BULLISH"
    assert result["confidence_score"] == pytest.approx(0.82)
    assert "reasoning_short" in result
    assert "risk_warning" in result
    assert result["model_used"] == "openai/gpt-oss-120b:free"


@pytest.mark.asyncio
async def test_domain_analyst_fallback_on_error(sample_analysis):
    """Analyst should return neutral on API failure."""
    analyst = DomainAnalyst("technical", model="openai/gpt-oss-120b:free")
    with patch.object(analyst.client, "_post_with_failover", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = RuntimeError("OpenRouter down")
        result = await analyst.analyze(sample_analysis)

    assert result["bias"] == "NEUTRAL"
    assert result["confidence_score"] == 0.0
    assert "error" in result["reasoning_short"].lower()


@pytest.mark.asyncio
async def test_lead_strategist_decision(sample_analysis):
    """Lead should produce a structured decision with zones."""
    lead = LeadStrategist(model="openai/gpt-oss-120b:free")
    with patch.object(lead.client, "_post_with_failover", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = (
            {"choices": [{"message": {"content": '{"decision": "BUY", "confidence": 0.78, "timeframe": "M5", "entry_zone": [1.0848, 1.0852], "sl_zone": [1.0840, 1.0842], "tp_zone": [1.0860, 1.0865], "position_size_pct": 1.0, "risk_reward": 2.0, "rationale": "EMA cross + bullish sentiment"}'}}]},
            "openai/gpt-oss-120b:free",
        )
        result = await lead.decide("EURUSD", "scalping", {"technical": sample_analysis["technical"]}, None)

    assert result["decision"] == "BUY"
    assert result["confidence"] == pytest.approx(0.78)
    assert result["entry_zone"] == [1.0848, 1.0852]
    assert result["sl_zone"] == [1.0840, 1.0842]
    assert result["tp_zone"] == [1.0860, 1.0865]
    assert result["risk_reward"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_verifier_veto():
    """Verifier should veto a poor setup."""
    verifier = Verifier(model="deepseek/deepseek-r1:free")
    proposal = {"decision": "BUY", "confidence": 0.4, "entry_zone": [1.0848, 1.0852], "sl_zone": [1.0840, 1.0842], "tp_zone": [1.0860, 1.0865], "risk_reward": 0.8, "rationale": "Weak signal"}
    opinions = {"technical": {"bias": "NEUTRAL", "confidence_score": 0.3, "reasoning_short": "", "risk_warning": ""}}

    with patch.object(verifier.client, "_post_with_failover", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = (
            {"choices": [{"message": {"content": '{"verdict": "VETO", "confidence": 0.85, "concerns": "Poor RR, low confidence", "suggested_changes": ""}'}}]},
            "deepseek/deepseek-r1:free",
        )
        result = await verifier.verify("EURUSD", "scalping", proposal, opinions, None)

    assert result["verdict"] == "VETO"
    assert result["confidence"] == pytest.approx(0.85)
    assert "Poor RR" in result["concerns"]


@pytest.mark.asyncio
async def test_team_decision_engine_veto(sample_analysis):
    """Team engine should downgrade decision to HOLD when verifier vetoes."""
    team = TeamDecisionEngine(
        technical_model="openai/gpt-oss-120b:free",
        lead_model="openai/gpt-oss-120b:free",
        verifier_model="deepseek/deepseek-r1:free",
        verifier_enabled=True,
        verifier_can_veto=True,
    )

    with patch.object(team.analysts["technical"], "analyze", new_callable=AsyncMock) as mock_tech, \
         patch.object(team.analysts["fundamental"], "analyze", new_callable=AsyncMock) as mock_fund, \
         patch.object(team.analysts["sentiment"], "analyze", new_callable=AsyncMock) as mock_sent, \
         patch.object(team.analysts["macro"], "analyze", new_callable=AsyncMock) as mock_macro, \
         patch.object(team.lead, "decide", new_callable=AsyncMock) as mock_lead, \
         patch.object(team.verifier, "verify", new_callable=AsyncMock) as mock_verifier:

        mock_tech.return_value = {"bias": "BULLISH", "confidence_score": 0.7, "reasoning_short": "", "risk_warning": ""}
        mock_fund.return_value = {"bias": "BULLISH", "confidence_score": 0.6, "reasoning_short": "", "risk_warning": ""}
        mock_sent.return_value = {"bias": "BULLISH", "confidence_score": 0.65, "reasoning_short": "", "risk_warning": ""}
        mock_macro.return_value = {"bias": "NEUTRAL", "confidence_score": 0.5, "reasoning_short": "", "risk_warning": ""}
        mock_lead.return_value = {
            "decision": "BUY", "confidence": 0.7, "timeframe": "M5",
            "entry_zone": [1.0848, 1.0852], "sl_zone": [1.0840, 1.0842], "tp_zone": [1.0860, 1.0865],
            "position_size_pct": 1.0, "risk_reward": 2.0,
            "rationale": "Test", "model_used": "lead-model",
        }
        mock_verifier.return_value = {"verdict": "VETO", "confidence": 0.9, "concerns": "Risk too high", "suggested_changes": "", "model_used": "verifier-model"}

        result = await team.decide("EURUSD", "scalping", sample_analysis)

    assert result["decision"] == "HOLD"
    assert result["verifier_verdict"] == "VETO"
    assert "VETOED" in result["rationale"]
    assert result["engine_version"] == "v2"


@pytest.mark.asyncio
async def test_team_decision_engine_approve(sample_analysis):
    """Team engine should keep BUY when verifier approves."""
    team = TeamDecisionEngine(
        technical_model="openai/gpt-oss-120b:free",
        lead_model="openai/gpt-oss-120b:free",
        verifier_model="deepseek/deepseek-r1:free",
        verifier_enabled=True,
        verifier_can_veto=True,
    )

    with patch.object(team.analysts["technical"], "analyze", new_callable=AsyncMock) as mock_tech, \
         patch.object(team.analysts["fundamental"], "analyze", new_callable=AsyncMock) as mock_fund, \
         patch.object(team.analysts["sentiment"], "analyze", new_callable=AsyncMock) as mock_sent, \
         patch.object(team.analysts["macro"], "analyze", new_callable=AsyncMock) as mock_macro, \
         patch.object(team.lead, "decide", new_callable=AsyncMock) as mock_lead, \
         patch.object(team.verifier, "verify", new_callable=AsyncMock) as mock_verifier:

        mock_tech.return_value = {"bias": "BULLISH", "confidence_score": 0.7, "reasoning_short": "", "risk_warning": ""}
        mock_fund.return_value = {"bias": "BULLISH", "confidence_score": 0.6, "reasoning_short": "", "risk_warning": ""}
        mock_sent.return_value = {"bias": "BULLISH", "confidence_score": 0.65, "reasoning_short": "", "risk_warning": ""}
        mock_macro.return_value = {"bias": "NEUTRAL", "confidence_score": 0.5, "reasoning_short": "", "risk_warning": ""}
        mock_lead.return_value = {
            "decision": "BUY", "confidence": 0.7, "timeframe": "M5",
            "entry_zone": [1.0848, 1.0852], "sl_zone": [1.0840, 1.0842], "tp_zone": [1.0860, 1.0865],
            "position_size_pct": 1.0, "risk_reward": 2.0,
            "rationale": "Test", "model_used": "lead-model",
        }
        mock_verifier.return_value = {"verdict": "APPROVE", "confidence": 0.9, "concerns": "", "suggested_changes": "", "model_used": "verifier-model"}

        result = await team.decide("EURUSD", "scalping", sample_analysis)

    assert result["decision"] == "BUY"
    assert result["verifier_verdict"] == "APPROVE"
    assert result["entry_price"] == pytest.approx(1.0850)  # midpoint of zone


@pytest.mark.asyncio
async def test_daily_bias_compute():
    """Daily bias compute should return structured output."""
    engine = DailyBiasEngine(model="deepseek/deepseek-r1:free")
    with patch.object(engine.client, "_post_with_failover", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = (
            {"choices": [{"message": {"content": '{"bias": "BULLISH", "confidence": 0.75, "rationale": "DXY weakness", "key_levels": [1.0840, 1.0870], "risk_events": ["US CPI"]}'}}]},
            "deepseek/deepseek-r1:free",
        )
        result = await engine.compute(
            symbol="EURUSD",
            macro_snapshot={"dxy_bias": "bearish"},
            news_summary="DXY down 0.5%",
        )

    assert result["bias"] == "BULLISH"
    assert result["confidence"] == pytest.approx(0.75)
    assert "computed_at" in result
    assert result["model_used"] == "deepseek/deepseek-r1:free"

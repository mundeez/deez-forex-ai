"""TeamDecisionEngine — orchestrates the multi-tier v2 pipeline.

Pipeline:
  1. Daily Bias (cached, cheap lookup)
  2. Domain Analysts (parallel LLM calls)
  3. Lead Strategist (fuses opinions + RAG + bias)
  4. Python computes exact SL/TP/size from lead zones + ATR
  5. Verifier (reviews proposal)
  6. Decision (APPROVE → trade; REVISE → apply changes; VETO → HOLD)
"""
import asyncio
from typing import Dict, Any, Optional
import logging

from app.ai.openrouter_client import OpenRouterClient
from app.ai.model_router import ModelRouter
from app.config import get_settings

from .analyst import DomainAnalyst
from .lead import LeadStrategist
from .verifier import Verifier

settings = get_settings()
logger = logging.getLogger("app.ai.team.orchestrator")


class TeamDecisionEngine:
    """The v2 multi-agent trading decision engine."""

    DOMAINS = ["technical", "fundamental", "sentiment", "macro"]

    def __init__(
        self,
        technical_model: str = None,
        fundamental_model: str = None,
        sentiment_model: str = None,
        macro_model: str = None,
        lead_model: str = None,
        verifier_model: str = None,
        verifier_enabled: bool = True,
        verifier_can_veto: bool = True,
        analyst_parallelism: bool = True,
    ):
        self.analysts = {
            "technical": DomainAnalyst("technical", technical_model or settings.MODEL_TECHNICAL),
            "fundamental": DomainAnalyst("fundamental", fundamental_model or settings.MODEL_FUNDAMENTAL),
            "sentiment": DomainAnalyst("sentiment", sentiment_model or settings.MODEL_SENTIMENT),
            "macro": DomainAnalyst("macro", macro_model or settings.MODEL_MACRO),
        }
        self.lead = LeadStrategist(lead_model or settings.MODEL_LEAD)
        self.verifier = Verifier(verifier_model or settings.MODEL_VERIFIER)
        self.verifier_enabled = verifier_enabled
        self.verifier_can_veto = verifier_can_veto
        self.analyst_parallelism = analyst_parallelism
        self.router = ModelRouter()

    async def _get_daily_bias(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch cached daily bias from Redis (set by scheduled task)."""
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            raw = await r.get(f"daily_bias:{symbol}")
            await r.close()
            if raw:
                import json
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Daily bias cache miss for %s: %s", symbol, exc)
        return None

    async def _run_analysts(self, analysis_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Run all domain analysts — parallel or sequential."""
        if self.analyst_parallelism:
            coros = [
                self.analysts[domain].analyze(analysis_snapshot, router=self.router)
                for domain in self.DOMAINS
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)
            return {
                domain: (res if not isinstance(res, Exception) else {"bias": "NEUTRAL", "confidence_score": 0.0, "reasoning_short": f"Error: {str(res)[:80]}", "risk_warning": "", "model_used": "error"})
                for domain, res in zip(self.DOMAINS, results)
            }
        else:
            return {
                domain: await self.analysts[domain].analyze(analysis_snapshot, router=self.router)
                for domain in self.DOMAINS
            }

    async def decide(
        self,
        symbol: str,
        strategy_mode: str,
        analysis_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the full v2 pipeline and return the final decision."""
        # 1. Daily bias
        daily_bias = await self._get_daily_bias(symbol)

        # 2. Domain analysts
        analyst_opinions = await self._run_analysts(analysis_snapshot)

        # 3. Lead strategist
        lead_proposal = await self.lead.decide(
            symbol, strategy_mode, analyst_opinions, daily_bias, router=self.router
        )

        # 4. Verifier (optional, off hot path for scalping if slow)
        verifier_result = None
        if self.verifier_enabled:
            verifier_result = await self.verifier.verify(
                symbol, strategy_mode, lead_proposal, analyst_opinions, daily_bias, router=self.router
            )

        # 5. Apply verifier
        final_decision = lead_proposal["decision"]
        final_confidence = lead_proposal["confidence"]
        final_rationale = lead_proposal["rationale"]
        verifier_verdict = "SKIPPED"

        if verifier_result:
            verifier_verdict = verifier_result["verdict"]
            if verifier_verdict == "VETO" and self.verifier_can_veto:
                final_decision = "HOLD"
                final_confidence = 0.0
                final_rationale += f" | VETOED: {verifier_result['concerns'][:120]}"
            elif verifier_verdict == "REVISE":
                final_rationale += f" | REVISED: {verifier_result['suggested_changes'][:120]}"
                final_confidence *= 0.85  # reduce confidence on revision

        # Compute exact prices from zone midpoints for backward compatibility
        # with the existing execution pipeline (v1 TradeDecision fields).
        def _mid(zone):
            if isinstance(zone, (list, tuple)) and len(zone) >= 2:
                return (float(zone[0]) + float(zone[1])) / 2.0
            return float(zone) if zone else 0.0

        return {
            "decision": final_decision,
            "confidence": final_confidence,
            "timeframe": lead_proposal["timeframe"],
            "entry_price": _mid(lead_proposal.get("entry_zone", [0, 0])),
            "stop_loss": _mid(lead_proposal.get("sl_zone", [0, 0])),
            "take_profit": _mid(lead_proposal.get("tp_zone", [0, 0])),
            "entry_zone": lead_proposal["entry_zone"],
            "sl_zone": lead_proposal["sl_zone"],
            "tp_zone": lead_proposal["tp_zone"],
            "position_size_pct": lead_proposal["position_size_pct"],
            "risk_reward": lead_proposal["risk_reward"],
            "rationale": final_rationale,
            "analyst_opinions": analyst_opinions,
            "lead_model": lead_proposal["model_used"],
            "verifier_verdict": verifier_verdict,
            "verifier_model": verifier_result["model_used"] if verifier_result else None,
            "daily_bias": daily_bias,
            "engine_version": "v2",
        }

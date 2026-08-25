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

from .analyst import DomainAnalyst
from .lead import LeadStrategist
from app.services.analyst_weight_optimizer import AnalystWeightOptimizer
from .verifier import Verifier

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
            "technical": DomainAnalyst("technical", technical_model or "deepseek/deepseek-v4-flash"),
            "fundamental": DomainAnalyst("fundamental", fundamental_model or "google/gemini-2.5-flash"),
            "sentiment": DomainAnalyst("sentiment", sentiment_model or "meta-llama/llama-3.3-70b-instruct"),
            "macro": DomainAnalyst("macro", macro_model or "openai/gpt-4o-mini"),
        }
        self.lead = LeadStrategist(lead_model or "deepseek/deepseek-v4-flash")
        self.verifier = Verifier(verifier_model or "deepseek/deepseek-r1")
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

        # 3. Lead strategist (with regime/session-aware analyst weights)
        regime = analysis_snapshot.get("regime", "unknown")
        session = analysis_snapshot.get("session", "unknown")
        weights_dict = await AnalystWeightOptimizer().get_cached_weights() or {}
        analyst_weights = AnalystWeightOptimizer.get_weights_for_context(
            weights_dict, regime=regime, session=session
        )
        lead_proposal = await self.lead.decide(
            symbol, strategy_mode, analyst_opinions, daily_bias,
            router=self.router, analyst_weights=analyst_weights
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

        # 6. Pattern-prior hard filter (adaptive win-rate threshold)
        try:
            from app.services.pattern_extractor import PatternExtractor
            pe = PatternExtractor()
            pattern_priors = await pe.get_cached_priors()
            if pattern_priors and final_decision in ("BUY", "SELL"):
                session = analysis_snapshot.get("session", "unknown")
                threshold = 0.30
                min_samples = 3
                by_session = pattern_priors.get("by_session", {})
                by_symbol_session = pattern_priors.get("by_symbol_session", {})
                by_symbol = pattern_priors.get("by_symbol", {})
                by_pair_dir = pattern_priors.get("by_symbol_direction", {})
                reasons = []
                # Prefer symbol-scoped session win rate; fall back to the
                # global session stat only when we lack enough symbol×session
                # samples. Otherwise one bad pair in a session would block
                # every other pair trading in that same session.
                ss = by_symbol_session.get(f"{symbol}_{session}", {})
                if ss.get("count", 0) >= min_samples and ss.get("win_rate", 1.0) < threshold:
                    reasons.append(f"{symbol} {session} WR {ss['win_rate']:.0%}")
                else:
                    s = by_session.get(session, {})
                    if s.get("count", 0) >= min_samples and s.get("win_rate", 1.0) < threshold:
                        reasons.append(f"session {session} WR {s['win_rate']:.0%}")
                s2 = by_symbol.get(symbol, {})
                if s2.get("count", 0) >= min_samples and s2.get("win_rate", 1.0) < threshold:
                    reasons.append(f"pair {symbol} WR {s2['win_rate']:.0%}")
                key = f"{symbol}_{final_decision}"
                s3 = by_pair_dir.get(key, {})
                if s3.get("count", 0) >= min_samples and s3.get("win_rate", 1.0) < threshold:
                    reasons.append(f"{key} WR {s3['win_rate']:.0%}")
                if reasons:
                    final_decision = "HOLD"
                    final_confidence *= 0.5
                    final_rationale += " [PATTERN FILTER: " + ", ".join(reasons) + "]"
        except Exception as exc:
            logger.warning("Pattern-prior hard filter failed for %s: %s", symbol, exc)
        def _mid(zone):
            if isinstance(zone, (list, tuple)):
                # Unwrap nested lists (models sometimes return [[price]])
                while isinstance(zone, list) and len(zone) == 1 and isinstance(zone[0], list):
                    zone = zone[0]
                if len(zone) >= 2:
                    v0 = float(zone[0]) if zone[0] is not None else 0.0
                    v1 = float(zone[1]) if zone[1] is not None else 0.0
                    return (v0 + v1) / 2.0
                if len(zone) == 1:
                    return float(zone[0]) if zone[0] is not None else 0.0
                return 0.0
            return float(zone) if zone is not None else 0.0

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
            "verifier_confidence": verifier_result["confidence"] if verifier_result else None,
            "verifier_model": verifier_result["model_used"] if verifier_result else None,
            "daily_bias": daily_bias,
            "engine_version": "v2",
        }

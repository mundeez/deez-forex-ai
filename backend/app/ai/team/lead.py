"""Lead Strategist — fuses analyst opinions, cached daily bias, and RAG into a trade proposal.

The Lead NEVER computes exact SL/TP/position size in its LLM prompt.
It proposes a directional trade with approximate levels; Python (RiskManager + ATR)
computes and validates the exact numbers afterwards.
"""
from typing import Dict, Any, Optional
import logging

from app.ai.openrouter_client import OpenRouterClient, normalize_decision
from app.ai.model_router import ModelRouter
from app.services.vector_store import VectorStore

logger = logging.getLogger("app.ai.team.lead")


class LeadStrategist:
    """Fuses multi-domain analyst opinions + RAG + daily bias into a trade proposal.

    Output schema:
      {
        "decision": "BUY|SELL|HOLD",
        "confidence": 0.0..1.0,
        "timeframe": "...",
        "entry_zone": [low, high],
        "sl_zone": [low, high],
        "tp_zone": [low, high],
        "position_size_pct": 1.0,
        "risk_reward": 1.0,
        "rationale": "...",
        "model_used": "..."
      }
    """

    _SYSTEM_PROMPT = (
        "You are an expert forex trading strategist. You fuse multiple analyst opinions, "
        "historical setup outcomes (RAG), and the current daily bias into a single trade decision. "
        "You NEVER compute exact stop-loss, take-profit, or position size. You propose approximate "
        "zones and direction. Python will compute exact values. Output ONLY a JSON object."
    )

    def __init__(self, model: str = None):
        self.model = model
        self.client = OpenRouterClient()

    def _build_prompt(
        self,
        symbol: str,
        strategy_mode: str,
        analyst_opinions: Dict[str, Any],
        daily_bias: Optional[Dict[str, Any]],
        similar_setups: list,
    ) -> str:
        prompt = (
            f"Symbol: {symbol}\n"
            f"Strategy: {strategy_mode.upper()}\n\n"
            "Analyst Opinions:\n"
        )
        for domain, opinion in analyst_opinions.items():
            prompt += (
                f"  [{domain.upper()}] bias={opinion.get('bias','NEUTRAL')}, "
                f"confidence={opinion.get('confidence_score',0):.0%}, "
                f"reasoning={opinion.get('reasoning_short','')[:120]}, "
                f"risk={opinion.get('risk_warning','')[:80]}\n"
            )

        if daily_bias:
            prompt += (
                f"\nDaily Bias: {daily_bias.get('bias','NEUTRAL')} "
                f"(confidence={daily_bias.get('confidence',0):.0%}, "
                f"rationale={daily_bias.get('rationale','')[:120]})\n"
            )

        if similar_setups:
            prompt += "\nSimilar Past Setups (last 90d):\n"
            for s in similar_setups[:5]:
                prompt += (
                    f"  decision={s.get('decision')}, outcome={s.get('outcome_status','unknown')}, "
                    f"pnl={s.get('outcome_pnl','N/A')}, confidence={s.get('confidence','N/A')}\n"
                )

        prompt += (
            "\n\nReturn ONLY a JSON object with exactly these keys:\n"
            '{"decision": "BUY|SELL|HOLD", "confidence": 0.0..1.0, "timeframe": "string", '
            '"entry_zone": [low, high], "sl_zone": [low, high], "tp_zone": [low, high], '
            '"position_size_pct": 1.0, "risk_reward": 1.0, "rationale": "string"}'
        )
        return prompt

    async def decide(
        self,
        symbol: str,
        strategy_mode: str,
        analyst_opinions: Dict[str, Any],
        daily_bias: Optional[Dict[str, Any]],
        router: Optional[ModelRouter] = None,
    ) -> Dict[str, Any]:
        # RAG: retrieve similar past setups
        similar = []
        try:
            vs = VectorStore()
            # Use the technical snapshot to encode for similarity
            from app.services.vector_store import COLLECTION_NAME
            tech_snapshot = {}
            if "technical" in analyst_opinions:
                tech_snapshot = {"technical": analyst_opinions.get("technical", {})}
            similar = vs.search_similar(tech_snapshot, limit=10)
        except Exception as exc:
            logger.warning("RAG search failed for lead: %s", exc)

        prompt = self._build_prompt(symbol, strategy_mode, analyst_opinions, daily_bias, similar)
        payload = {
            "temperature": 0.15,
            "max_tokens": 384,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            data, used_model = await self.client._post_with_failover(
                self.client._request_headers(),
                payload,
                [self.model] if self.model else [self.client.model],
                router=router,
            )
            content = data["choices"][0]["message"]["content"]
            parsed = self.client._parse_object(content)
        except Exception as exc:
            logger.error("Lead strategist failed: %s", exc, exc_info=True)
            return self._fallback(symbol, strategy_mode, str(exc))

        return {
            "decision": normalize_decision(parsed.get("decision")),
            "confidence": float(parsed.get("confidence") or 0.0),
            "timeframe": parsed.get("timeframe", "M5" if strategy_mode == "scalping" else "H1"),
            "entry_zone": parsed.get("entry_zone", [0.0, 0.0]),
            "sl_zone": parsed.get("sl_zone", [0.0, 0.0]),
            "tp_zone": parsed.get("tp_zone", [0.0, 0.0]),
            "position_size_pct": float(parsed.get("position_size_pct") or 1.0),
            "risk_reward": float(parsed.get("risk_reward") or 1.0),
            "rationale": parsed.get("rationale", ""),
            "model_used": used_model,
        }

    def _fallback(self, symbol: str, strategy_mode: str, error: str) -> Dict[str, Any]:
        return {
            "decision": "HOLD",
            "confidence": 0.0,
            "timeframe": "M5" if strategy_mode == "scalping" else "H1",
            "entry_zone": [0.0, 0.0],
            "sl_zone": [0.0, 0.0],
            "tp_zone": [0.0, 0.0],
            "position_size_pct": 0.0,
            "risk_reward": 0.0,
            "rationale": f"Lead fallback: {error[:120]}",
            "model_used": self.model or "fallback",
        }

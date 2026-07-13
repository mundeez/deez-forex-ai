"""Verifier — DeepSeek-R1 "Risk Manager" agent.

Reviews a proposed trade setup and finds flaws across fundamental and technical
lines. Can APPROVE, REVISE (suggest changes), or VETO.

For scalping: use a fast model (sampled / lightweight).
For swing / exit re-eval: use DeepSeek-R1 for deep reasoning.
"""
from typing import Dict, Any, Optional
import logging

from app.ai.openrouter_client import OpenRouterClient, _safe_float_conf
from app.ai.model_router import ModelRouter

logger = logging.getLogger("app.ai.team.verifier")


class Verifier:
    """Risk-manager verifier.

    Prompt (Gemini doc aligned): "Find the flaws in this setup across fundamental and technical lines."

    Output schema:
      {
        "verdict": "APPROVE|REVISE|VETO",
        "confidence": 0.0..1.0,
        "concerns": "string",
        "suggested_changes": "string or empty",
        "model_used": "..."
      }
    """

    _SYSTEM_PROMPT = (
        "You are a balanced risk manager reviewing a proposed forex paper trade. "
        "Review the setup across fundamental and technical lines. "
        "Only VETO if there are CRITICAL flaws: missing entry/SL/TP, extreme news risk, "
        "or clear signal contradiction (e.g., BUY when all analysts say SELL). "
        "Use REVISE for moderate concerns (tighten SL, reduce size, adjust entry). "
        "APPROVE when the trade has a reasonable thesis with defined risk parameters. "
        "Remember: this is paper trading — favor allowing trades with managed risk "
        "over blocking them entirely. Missing parameters on a HOLD proposal is not a flaw. "
        "Return ONLY a JSON object with keys: verdict (APPROVE|REVISE|VETO), "
        "confidence (0.0-1.0), concerns (string), suggested_changes (string or empty)."
    )

    def __init__(self, model: str = None):
        self.model = model
        self.client = OpenRouterClient()

    def _build_prompt(
        self,
        symbol: str,
        strategy_mode: str,
        proposal: Dict[str, Any],
        analyst_opinions: Dict[str, Any],
        daily_bias: Optional[Dict[str, Any]],
    ) -> str:
        prompt = (
            f"Proposed Trade:\n"
            f"  Symbol: {symbol}\n"
            f"  Strategy: {strategy_mode}\n"
            f"  Decision: {proposal.get('decision', 'HOLD')}\n"
            f"  Confidence: {proposal.get('confidence', 0):.0%}\n"
            f"  Entry Zone: {proposal.get('entry_zone', [0,0])}\n"
            f"  SL Zone: {proposal.get('sl_zone', [0,0])}\n"
            f"  TP Zone: {proposal.get('tp_zone', [0,0])}\n"
            f"  Rationale: {proposal.get('rationale', '')[:200]}\n\n"
            "Analyst Opinions:\n"
        )
        for domain, opinion in analyst_opinions.items():
            prompt += (
                f"  [{domain.upper()}] {opinion.get('bias','NEUTRAL')} @ "
                f"{opinion.get('confidence_score',0):.0%} — {opinion.get('reasoning_short','')[:100]}\n"
            )
        if daily_bias:
            prompt += (
                f"\nDaily Bias: {daily_bias.get('bias','NEUTRAL')} @ "
                f"{daily_bias.get('confidence',0):.0%}\n"
            )
        prompt += (
            "\n\nNow find the flaws. Return ONLY the JSON object."
        )
        return prompt

    async def verify(
        self,
        symbol: str,
        strategy_mode: str,
        proposal: Dict[str, Any],
        analyst_opinions: Dict[str, Any],
        daily_bias: Optional[Dict[str, Any]],
        router: Optional[ModelRouter] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(symbol, strategy_mode, proposal, analyst_opinions, daily_bias)
        payload = {
            "temperature": 0.1,
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
            logger.warning("Verifier failed (%s), returning APPROVE fallback", exc)
            return {
                "verdict": "APPROVE",
                "confidence": 0.0,
                "concerns": f"Verifier error: {str(exc)[:80]}",
                "suggested_changes": "",
                "model_used": self.model or "unknown",
            }

        verdict = str(parsed.get("verdict", "APPROVE")).upper()
        if verdict not in ("APPROVE", "REVISE", "VETO"):
            verdict = "APPROVE"

        return {
            "verdict": verdict,
            "confidence": _safe_float_conf(parsed.get("confidence")),
            "concerns": parsed.get("concerns", ""),
            "suggested_changes": parsed.get("suggested_changes", ""),
            "model_used": used_model,
        }

"""Domain-specific AI analysts.

Each analyst runs a single LLM call for its domain (technical, fundamental,
sentiment, macro), consuming pre-computed Python analysis snapshots and
returning a structured opinion.
"""
from typing import Dict, Any, Optional
import logging

from app.ai.openrouter_client import OpenRouterClient
from app.ai.model_router import ModelRouter

logger = logging.getLogger("app.ai.team.analyst")


class DomainAnalyst:
    """Run a single-domain AI analysis call.

    Output schema (Gemini-doc aligned):
      {
        "bias": "BULLISH|BEARISH|NEUTRAL",
        "confidence_score": 0.78,
        "reasoning_short": "...",
        "risk_warning": "...",
        "model_used": "..."
      }
    """

    _SYSTEM_PROMPT_TEMPLATE = (
        "You are a deterministic financial analysis engine executing high-frequency data parsing. "
        "You do not use conversational filler. You analyze inputs purely based on mathematical indicators, "
        "order flow, and specified fundamental sentiment. You must output exclusively in valid JSON format "
        "matching the schema requested."
    )

    def __init__(self, domain: str, model: str = None):
        self.domain = domain
        self.model = model
        self.client = OpenRouterClient()

    def _build_prompt(self, analysis_snapshot: Dict[str, Any]) -> str:
        prompt = (
            f"Domain: {self.domain.upper()}\n"
            f"Symbol: {analysis_snapshot.get('symbol', 'EURUSD')}\n"
            f"Timeframe: {analysis_snapshot.get('timeframe', 'M5')}\n\n"
        )
        # Inject pre-computed Python indicators as structured data
        if self.domain == "technical":
            prompt += self._technical_block(analysis_snapshot)
        elif self.domain == "fundamental":
            prompt += self._fundamental_block(analysis_snapshot)
        elif self.domain == "sentiment":
            prompt += self._sentiment_block(analysis_snapshot)
        elif self.domain == "macro":
            prompt += self._macro_block(analysis_snapshot)

        prompt += (
            "\n\nReturn ONLY a JSON object with exactly these keys:\n"
            '{"bias": "BULLISH|BEARISH|NEUTRAL", "confidence_score": 0.0..1.0, '
            '"reasoning_short": "string", "risk_warning": "string or empty"}'
        )
        return prompt

    @staticmethod
    def _technical_block(snapshot: Dict[str, Any]) -> str:
        tech = snapshot.get("technical", {})
        tfs = tech.get("timeframes", {})
        parts = []
        for tf, data in tfs.items():
            ind = data.get("indicators", {})
            parts.append(
                f"  {tf}: signal={data.get('signal','neutral')}, confidence={data.get('confidence',0):.0%}, "
                f"rsi={ind.get('rsi_14','N/A')}, ema9={ind.get('ema_9','N/A')}, "
                f"ema21={ind.get('ema_21','N/A')}, adx={ind.get('adx_14','N/A')}, "
                f"atr={ind.get('atr_14','N/A')}, bb_squeeze={data.get('bb_squeeze',False)}"
            )
        return "Technical:\n" + "\n".join(parts)

    @staticmethod
    def _fundamental_block(snapshot: Dict[str, Any]) -> str:
        fund = snapshot.get("fundamental", {})
        events = fund.get("events", [])
        event_str = "; ".join([e.get("title", "") for e in events[:3]]) if events else "none"
        return (
            f"Fundamental: bias={fund.get('direction_bias','neutral')}, "
            f"event_risk={fund.get('event_risk','low')}, "
            f"rate_spread={fund.get('interest_rate_spread','N/A')}, "
            f"events={event_str}"
        )

    @staticmethod
    def _sentiment_block(snapshot: Dict[str, Any]) -> str:
        sent = snapshot.get("sentiment", {})
        return (
            f"Sentiment: overall={sent.get('overall_sentiment','neutral')}, "
            f"score={sent.get('sentiment_score',0):.2f}"
        )

    @staticmethod
    def _macro_block(snapshot: Dict[str, Any]) -> str:
        macro = snapshot.get("macro", {})
        return (
            f"Macro: dxy_bias={macro.get('dxy_bias','neutral')}, "
            f"risk_on_score={macro.get('risk_on_score',0):.2f}, "
            f"rate_cycle={macro.get('rate_cycle','neutral')}, "
            f"correlations={macro.get('correlations','N/A')}"
        )

    async def analyze(
        self,
        analysis_snapshot: Dict[str, Any],
        router: Optional[ModelRouter] = None,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(analysis_snapshot)
        payload = {
            "temperature": 0.1,
            "max_tokens": 256,
            "messages": [
                {"role": "system", "content": self._SYSTEM_PROMPT_TEMPLATE},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            data, used_model = await self.client._post_with_failover(
                self.client._request_headers(),
                {**payload, "model": self.model} if self.model else payload,
                [self.model] if self.model else [self.client.model],
                router=router,
            )
            content = data["choices"][0]["message"]["content"]
            parsed = self.client._parse_object(content)
        except Exception as exc:
            logger.warning("%s analyst failed (%s), returning neutral", self.domain, exc, exc_info=True)
            return {
                "bias": "NEUTRAL",
                "confidence_score": 0.0,
                "reasoning_short": f"Analyst error: {str(exc)[:80]}",
                "risk_warning": "",
                "model_used": self.model or "unknown",
            }

        return {
            "bias": str(parsed.get("bias", "NEUTRAL")).upper(),
            "confidence_score": float(parsed.get("confidence_score") or 0.0),
            "reasoning_short": parsed.get("reasoning_short", ""),
            "risk_warning": parsed.get("risk_warning", ""),
            "model_used": used_model,
        }

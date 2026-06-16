"""TradeManagerAgent — LLM-based exit advisor.

Analyzes open positions and recommends HOLD, CLOSE, or PARTIAL_CLOSE
based on current market context, daily bias, and technical state.
Operates in alert-only mode by default (does not auto-execute).
"""
import json
import logging
from typing import Dict, Any, Optional

from app.ai.openrouter_client import OpenRouterClient
from app.ai.model_router import ModelRouter
from app.utils.time import utc_now

logger = logging.getLogger("app.ai.team.trade_manager")


class TradeManagerAgent:
    """AI exit advisor for open positions."""

    _SYSTEM_PROMPT = (
        "You are a disciplined trade manager. Given the current state of an open position, "
        "market context, and technical indicators, recommend ONE action. "
        "Output ONLY a JSON object with keys: "
        "action (HOLD|CLOSE|PARTIAL_CLOSE), confidence (0.0-1.0), "
        "reasoning (string), suggested_sl (number or null), suggested_tp (number or null), "
        "close_pct (0.0-1.0, only if PARTIAL_CLOSE)."
    )

    def __init__(self, model: str = None):
        self.model = model or "deepseek/deepseek-r1:free"
        self.client = OpenRouterClient()

    async def advise(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        current_price: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        pnl: float,
        pnl_pct: float,
        duration_min: int,
        analysis_snapshot: Dict[str, Any],
        daily_bias: Optional[Dict[str, Any]] = None,
        router: Optional[ModelRouter] = None,
    ) -> Dict[str, Any]:
        """Get AI exit recommendation for an open position."""
        tech = analysis_snapshot.get("technical", {})
        tfs = tech.get("timeframes", {})
        primary = next(iter(tfs.values()), {}) if tfs else {}
        ind = primary.get("indicators", {})

        prompt = (
            f"Symbol: {symbol}\n"
            f"Position: {direction.upper()} @ {entry_price}\n"
            f"Current price: {current_price}\n"
            f"PnL: {pnl:.2f} ({pnl_pct:.2f}%)\n"
            f"Duration: {duration_min}m\n"
            f"SL: {stop_loss}\n"
            f"TP: {take_profit}\n\n"
            f"Technical: rsi={ind.get('rsi_14','N/A')}, adx={ind.get('adx_14','N/A')}, "
            f"macd_hist={ind.get('macd_hist','N/A')}, stoch_k={ind.get('stoch_k','N/A')}\n"
        )
        if daily_bias:
            prompt += (
                f"Daily bias: {daily_bias.get('bias','NEUTRAL')} "
                f"({daily_bias.get('confidence',0):.0%})\n"
            )

        payload = {
            "temperature": 0.15,
            "max_tokens": 256,
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
                [self.model],
                router=router,
            )
            content = data["choices"][0]["message"]["content"]
            parsed = self.client._parse_object(content)
        except Exception as exc:
            logger.error("TradeManagerAgent failed for %s: %s", symbol, exc, exc_info=True)
            return {
                "action": "HOLD",
                "confidence": 0.0,
                "reasoning": f"Error: {str(exc)[:80]}",
                "suggested_sl": None,
                "suggested_tp": None,
                "close_pct": None,
                "model_used": self.model,
            }

        return {
            "action": str(parsed.get("action", "HOLD")).upper(),
            "confidence": float(parsed.get("confidence") or 0.0),
            "reasoning": parsed.get("reasoning", ""),
            "suggested_sl": parsed.get("suggested_sl"),
            "suggested_tp": parsed.get("suggested_tp"),
            "close_pct": parsed.get("close_pct"),
            "model_used": used_model,
        }

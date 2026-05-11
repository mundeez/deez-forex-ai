import json
import httpx
from typing import Dict, Any
from pydantic import BaseModel
from app.config import get_settings

settings = get_settings()


class TradeDecision(BaseModel):
    decision: str
    confidence: float
    timeframe: str = "H1"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size_pct: float = 1.0
    risk_reward: float = 1.0
    rationale: str = ""
    symbol: str = "EURUSD"


class OpenRouterClient:
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = settings.OPENROUTER_MODEL
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    async def get_trade_decision(self, analysis: Dict[str, Any]) -> TradeDecision:
        if not self.api_key:
            return self._fallback_decision(analysis)

        prompt = self._build_prompt(analysis)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://deez-forex-ai.local",
            "X-Title": "deez-forex-ai",
        }
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert forex trading analyst AI. Analyze the provided market data and output "
                        "a JSON object with these exact keys: decision (BUY, SELL, or HOLD), confidence (0.0-1.0), "
                        "timeframe (e.g., H1), entry_price, stop_loss, take_profit, position_size_pct (risk %), "
                        "risk_reward, rationale (string). Ensure the JSON is valid and contains no extra commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.base_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = self._extract_json(content)

        return TradeDecision(
            decision=parsed.get("decision", "HOLD").upper(),
            confidence=float(parsed.get("confidence", 0.0)),
            timeframe=parsed.get("timeframe", "H1"),
            entry_price=float(parsed.get("entry_price", 0.0)),
            stop_loss=float(parsed.get("stop_loss", 0.0)),
            take_profit=float(parsed.get("take_profit", 0.0)),
            position_size_pct=float(parsed.get("position_size_pct", 1.0)),
            risk_reward=float(parsed.get("risk_reward", 1.0)),
            rationale=parsed.get("rationale", "No rationale provided."),
            symbol=analysis.get("symbol", "EURUSD"),
        )

    def _build_prompt(self, analysis: Dict[str, Any]) -> str:
        tech = analysis.get("technical", {})
        fund = analysis.get("fundamental", {})
        sent = analysis.get("sentiment", {})
        return (
            f"Symbol: {analysis.get('symbol', 'EURUSD')}\n\n"
            f"TECHNICAL ANALYSIS:\n"
            f"- Overall signal: {tech.get('overall_signal', 'neutral')}\n"
            f"- 1H: {json.dumps(tech.get('timeframes', {}).get('1h', {}), indent=2)}\n"
            f"- 4H: {json.dumps(tech.get('timeframes', {}).get('4h', {}), indent=2)}\n"
            f"- 1D: {json.dumps(tech.get('timeframes', {}).get('1d', {}), indent=2)}\n\n"
            f"FUNDAMENTAL ANALYSIS:\n"
            f"- Event risk: {fund.get('event_risk', 'low')}\n"
            f"- Interest rate spread: {fund.get('interest_rate_spread', 'N/A')}\n"
            f"- Direction bias: {fund.get('direction_bias', 'neutral')}\n"
            f"- Upcoming events: {json.dumps(fund.get('events', []), indent=2)}\n\n"
            f"SENTIMENT ANALYSIS:\n"
            f"- Overall: {sent.get('overall_sentiment', 'neutral')} (score: {sent.get('sentiment_score', 0)})\n"
            f"- Retail: {json.dumps(sent.get('retail', {}), indent=2)}\n"
            f"- News: {json.dumps(sent.get('news', {}), indent=2)}\n"
            f"- Institutional: {json.dumps(sent.get('institutional', {}), indent=2)}\n\n"
            "Provide a JSON trade decision with entry, stop loss, take profit, confidence, and rationale."
        )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
        return {}

    def _fallback_decision(self, analysis: Dict[str, Any]) -> TradeDecision:
        import random
        tech = analysis.get("technical", {})
        signal = tech.get("overall_signal", "neutral")
        if signal == "bullish":
            dec = "BUY"
        elif signal == "bearish":
            dec = "SELL"
        else:
            dec = random.choice(["BUY", "SELL", "HOLD"])

        base = 1.0850
        return TradeDecision(
            decision=dec,
            confidence=round(random.uniform(0.55, 0.75), 2),
            timeframe="H1",
            entry_price=round(base, 5),
            stop_loss=round(base - 0.0030, 5) if dec == "BUY" else round(base + 0.0030, 5),
            take_profit=round(base + 0.0050, 5) if dec == "BUY" else round(base - 0.0050, 5),
            position_size_pct=1.5,
            risk_reward=1.67,
            rationale="[FALLBACK] OpenRouter API key not configured. Using technical signal only.",
            symbol=analysis.get("symbol", "EURUSD"),
        )

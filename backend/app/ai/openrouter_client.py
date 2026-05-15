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

    def _system_prompt(self, strategy_mode: str) -> str:
        base = (
            "You are an expert forex trading analyst AI. Analyze the provided market data and output "
            "a JSON object with these exact keys: decision (BUY, SELL, or HOLD), confidence (0.0-1.0), "
            "timeframe, entry_price, stop_loss, take_profit, position_size_pct (risk %), "
            "risk_reward, rationale (string). Ensure the JSON is valid and contains no extra commentary."
        )
        if strategy_mode == "scalping":
            return (
                base + "\n\nSTRATEGY: SCALPING. Rules:\n"
                "1. Only trade when VWAP and EMA alignment confirm direction on 1m/5m.\n"
                "2. Stop loss must be tight: 1.0-1.5x ATR (max 10 pips).\n"
                "3. Take profit: 1.5-2.0x ATR (8-15 pips). Risk:Reward should be ~1.0-1.5.\n"
                "4. Avoid trades when ADX < 20 (weak trend / chop).\n"
                "5. If Bollinger squeeze detected, expect breakout — enter on momentum confirmation.\n"
                "6. Position size: 0.5-1.0% risk per trade.\n"
                "7. HOLD if no clear setup within 3-5 pips of entry zone.\n"
                "8. Prefer trades during London/NY overlap (08:00-17:00 UTC)."
            )
        elif strategy_mode == "day_trading":
            return (
                base + "\n\nSTRATEGY: DAY TRADING. Rules:\n"
                "1. Trade 15m trend aligned with 1h context. 5m for precise entry.\n"
                "2. Stop loss: 1.5-2.5x ATR (15-30 pips).\n"
                "3. Take profit: 2.5-4.0x ATR (30-60 pips). Risk:Reward min 1.5.\n"
                "4. Avoid counter-trend trades against 1h EMA50.\n"
                "5. Check event risk — no new trades within 30 min of high-impact news.\n"
                "6. Position size: 1.0-1.5% risk per trade.\n"
                "7. Close all trades before 21:30 UTC (end of day)."
            )
        else:  # swing
            return (
                base + "\n\nSTRATEGY: SWING TRADING. Rules:\n"
                "1. Trade only when 1h, 4h, and 1D all align.\n"
                "2. Stop loss: 2.5-4.0x ATR (50-100 pips).\n"
                "3. Take profit: 3.0-6.0x ATR (100-200 pips). Risk:Reward min 2.0.\n"
                "4. Fundamental direction must support technical signal.\n"
                "5. Position size: 1.5-2.0% risk per trade.\n"
                "6. Ignore noise — only high-confidence setups."
            )

    async def get_trade_decision(self, analysis: Dict[str, Any], strategy_mode: str = "scalping") -> TradeDecision:
        if not self.api_key:
            return self._fallback_decision(analysis, strategy_mode)

        prompt = self._build_prompt(analysis, strategy_mode)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://deez-forex-ai.local",
            "X-Title": "deez-forex-ai",
        }
        payload = {
            "model": self.model,
            "temperature": 0.15,
            "max_tokens": 512,
            "messages": [
                {"role": "system", "content": self._system_prompt(strategy_mode)},
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
            timeframe=parsed.get("timeframe", "M5" if strategy_mode == "scalping" else "H1"),
            entry_price=float(parsed.get("entry_price", 0.0)),
            stop_loss=float(parsed.get("stop_loss", 0.0)),
            take_profit=float(parsed.get("take_profit", 0.0)),
            position_size_pct=float(parsed.get("position_size_pct", 1.0)),
            risk_reward=float(parsed.get("risk_reward", 1.0)),
            rationale=parsed.get("rationale", "No rationale provided."),
            symbol=analysis.get("symbol", "EURUSD"),
        )

    def _build_prompt(self, analysis: Dict[str, Any], strategy_mode: str) -> str:
        tech = analysis.get("technical", {})
        fund = analysis.get("fundamental", {})
        sent = analysis.get("sentiment", {})
        tfs = tech.get("timeframes", {})

        tf_blocks = []
        for tf_name, tf_data in tfs.items():
            tf_blocks.append(f"- {tf_name.upper()}: {json.dumps(tf_data, indent=2)}")

        prompt = (
            f"Symbol: {analysis.get('symbol', 'EURUSD')}\n"
            f"Strategy: {strategy_mode.upper()}\n\n"
            f"TECHNICAL ANALYSIS:\n"
            f"- Overall signal: {tech.get('overall_signal', 'neutral')}\n"
            + "\n".join(tf_blocks) + "\n\n"
        )

        if strategy_mode != "scalping":
            prompt += (
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
            )
        else:
            # For scalping, keep fundamental/sentiment brief
            prompt += (
                f"MARKET CONTEXT:\n"
                f"- Event risk: {fund.get('event_risk', 'low')}\n"
                f"- Sentiment: {sent.get('overall_sentiment', 'neutral')}\n\n"
            )

        prompt += "Provide a JSON trade decision with entry, stop loss, take profit, confidence, and rationale."
        return prompt

    def _extract_json(self, text: str) -> Dict[str, Any]:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
        return {}

    def _fallback_decision(self, analysis: Dict[str, Any], strategy_mode: str = "scalping") -> TradeDecision:
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
        close = base
        tfs = tech.get("timeframes", {})
        for tf in tfs.values():
            ind = tf.get("indicators", {})
            if ind.get("close"):
                close = ind["close"]
                break

        if strategy_mode == "scalping":
            sl_dist = 0.0008
            tp_dist = 0.0012
            rr = 1.5
            timeframe = "M5"
            pos_size = 0.8
        elif strategy_mode == "day_trading":
            sl_dist = 0.0020
            tp_dist = 0.0040
            rr = 2.0
            timeframe = "H1"
            pos_size = 1.2
        else:
            sl_dist = 0.0050
            tp_dist = 0.0100
            rr = 2.0
            timeframe = "H4"
            pos_size = 1.5

        return TradeDecision(
            decision=dec,
            confidence=round(random.uniform(0.55, 0.75), 2),
            timeframe=timeframe,
            entry_price=round(close, 5),
            stop_loss=round(close - sl_dist, 5) if dec == "BUY" else round(close + sl_dist, 5),
            take_profit=round(close + tp_dist, 5) if dec == "BUY" else round(close - tp_dist, 5),
            position_size_pct=pos_size,
            risk_reward=rr,
            rationale=f"[FALLBACK] OpenRouter API key not configured. Using {strategy_mode} technical signal only.",
            symbol=analysis.get("symbol", "EURUSD"),
        )

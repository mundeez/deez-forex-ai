import asyncio
import json
import logging
import httpx
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
from app.config import get_settings
from app.ai.model_router import ModelRouter, RATE_LIMIT_STATUSES, SERVER_ERROR_STATUSES

settings = get_settings()
logger = logging.getLogger("app.ai.openrouter")


def normalize_decision(value: Any) -> str:
    """Coerce any model output into exactly BUY / SELL / HOLD.

    Free models occasionally emit malformed values like ": HOLD", ":SELL" or
    bare punctuation. We extract the first recognised token and default to HOLD.
    """
    if value is None:
        return "HOLD"
    v = str(value).upper()
    for token in ("BUY", "SELL", "HOLD"):
        if token in v:
            return token
    return "HOLD"


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
    model_used: str = ""


class OpenRouterClient:
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = settings.OPENROUTER_MODEL
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def _system_prompt(self, strategy_mode: str, aggressiveness: str = "moderate") -> str:
        base = (
            "You are an expert forex trading analyst AI. Analyze the provided market data and output "
            "a JSON object with these exact keys: decision (BUY, SELL, or HOLD), confidence (0.0-1.0), "
            "timeframe, entry_price, stop_loss, take_profit, position_size_pct (risk %), "
            "risk_reward, rationale (string). Ensure the JSON is valid and contains no extra commentary."
        )

        # Aggressiveness modifiers
        if aggressiveness == "aggressive":
            base += (
                "\n\nAGGRESSIVE MODE: Prefer action over inaction. When indicators show any directional "
                "bias, lean toward BUY or SELL rather than HOLD. Accept lower confidence setups (0.40+). "
                "Wider stops are acceptable. Higher risk per trade (up to 2%). "
                "The goal is to capture more opportunities even with slightly lower win rate."
            )
        elif aggressiveness == "conservative":
            base += (
                "\n\nCONSERVATIVE MODE: Only trade high-conviction setups. Require strong multi-timeframe "
                "alignment before recommending BUY or SELL. Default to HOLD unless the setup is excellent. "
                "Tight stops, smaller position sizes (0.5-1%). Prioritize capital preservation."
            )

        if strategy_mode == "scalping":
            return (
                base + "\n\nSTRATEGY: SCALPING. Rules:\n"
                "1. Only trade when VWAP and EMA alignment confirm direction on 1m/5m.\n"
                "2. Stop loss must be tight: 1.0-1.5x ATR (max 10 pips).\n"
                "3. Take profit: 1.5-2.0x ATR (8-15 pips). Risk:Reward should be ~1.0-1.5.\n"
                "4. Avoid trades when ADX < 15 (very weak trend / chop).\n"
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

    def _request_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://deez-forex-ai.local",
            "X-Title": "deez-forex-ai",
        }

    async def _resolve_candidates(self, router: Optional[ModelRouter], model_override: Optional[str]) -> List[str]:
        """Ordered list of models to attempt for a single request."""
        if router is not None:
            return await router.get_candidates(primary=model_override or self.model)
        return [model_override or self.model]

    async def get_trade_decision(
        self,
        analysis: Dict[str, Any],
        strategy_mode: str = "scalping",
        model_override: str = None,
        aggressiveness: str = "moderate",
        router: Optional[ModelRouter] = None,
    ) -> TradeDecision:
        if not self.api_key:
            return self._fallback_decision(analysis, strategy_mode)

        prompt = self._build_prompt(analysis, strategy_mode)
        payload = {
            "temperature": 0.15,
            "max_tokens": 384,  # Reduced from 512 — structured JSON needs far less
            "messages": [
                {"role": "system", "content": self._system_prompt(strategy_mode, aggressiveness)},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        candidates = await self._resolve_candidates(router, model_override)
        data, used_model = await self._post_with_failover(self._request_headers(), payload, candidates, router)

        content = data["choices"][0]["message"]["content"]
        parsed = self._parse_object(content)

        return TradeDecision(
            decision=normalize_decision(parsed.get("decision")),
            confidence=float(parsed.get("confidence") or 0.0),
            timeframe=parsed.get("timeframe", "M5" if strategy_mode == "scalping" else "H1"),
            entry_price=float(parsed.get("entry_price") or 0.0),
            stop_loss=float(parsed.get("stop_loss") or 0.0),
            take_profit=float(parsed.get("take_profit") or 0.0),
            position_size_pct=float(parsed.get("position_size_pct") or 1.0),
            risk_reward=float(parsed.get("risk_reward") or 1.0),
            rationale=parsed.get("rationale", "No rationale provided."),
            symbol=analysis.get("symbol", "EURUSD"),
            model_used=used_model,
        )

    async def _post_with_failover(
        self,
        headers: Dict[str, str],
        base_payload: Dict[str, Any],
        candidates: List[str],
        router: Optional[ModelRouter] = None,
    ) -> Tuple[Dict[str, Any], str]:
        """POST to OpenRouter, failing over across candidate models.

        Rate-limit / quota errors (402/403/429) put the model on cooldown (when a
        router is supplied) and immediately move to the next candidate. Transient
        server / network errors get one short retry on the same model before
        failing over. Returns the parsed JSON response and the model that served it.
        """
        last_exc: Optional[Exception] = None
        for model in candidates:
            payload = {**base_payload, "model": model}
            for attempt in range(2):  # up to 2 tries per model for transient errors
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post(self.base_url, headers=headers, json=payload)
                        resp.raise_for_status()
                        return resp.json(), model
                except httpx.HTTPStatusError as e:
                    last_exc = e
                    status = e.response.status_code
                    if status in RATE_LIMIT_STATUSES:
                        if router is not None:
                            await router.mark_cooldown(model)
                        logger.warning("Model %s rate-limited (%s); failing over to next model", model, status)
                        break  # don't retry this model — move to next candidate
                    if status in SERVER_ERROR_STATUSES and attempt == 0:
                        await asyncio.sleep(1.5)
                        continue
                    logger.warning("Model %s returned %s; failing over", model, status)
                    break
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    last_exc = e
                    if attempt == 0:
                        await asyncio.sleep(1.5)
                        continue
                    logger.warning("Model %s connection error: %s; failing over", model, e)
                    break
        if last_exc:
            raise last_exc
        raise RuntimeError("No OpenRouter model candidates available")

    def _compress_timeframe(self, tf_data: Dict[str, Any]) -> str:
        """Compress timeframe analysis to ~30 tokens instead of 500+."""
        signal = tf_data.get("signal", "neutral")
        confidence = tf_data.get("confidence", 0.0)
        ind = tf_data.get("indicators", {})
        parts = [f"sig:{signal}({confidence:.0%})"]
        # Only include key indicators that matter for the decision
        if ind.get("rsi_14") is not None:
            parts.append(f"RSI:{ind['rsi_14']:.0f}")
        if ind.get("ema_9") is not None and ind.get("ema_21") is not None:
            parts.append(f"EMA9{'>' if ind['ema_9'] > ind['ema_21'] else '<'}21")
        if ind.get("macd_hist") is not None:
            parts.append(f"MACD:{ind['macd_hist']:+.4f}")
        if ind.get("adx_14") is not None:
            parts.append(f"ADX:{ind['adx_14']:.0f}")
        if ind.get("bb_squeeze"):
            parts.append("BB_SQUEEZE")
        if ind.get("atr_14") is not None:
            parts.append(f"ATR:{ind['atr_14']:.5f}")
        support = tf_data.get("support")
        resistance = tf_data.get("resistance")
        if support and resistance:
            parts.append(f"S:{support:.5f} R:{resistance:.5f}")
        return " ".join(parts)

    def _build_prompt(self, analysis: Dict[str, Any], strategy_mode: str) -> str:
        tech = analysis.get("technical", {})
        fund = analysis.get("fundamental", {})
        sent = analysis.get("sentiment", {})
        tfs = tech.get("timeframes", {})

        tf_blocks = []
        for tf_name, tf_data in tfs.items():
            compressed = self._compress_timeframe(tf_data)
            tf_blocks.append(f"  {tf_name.upper()}: {compressed}")

        prompt = (
            f"Symbol: {analysis.get('symbol', 'EURUSD')}\n"
            f"Strategy: {strategy_mode.upper()}\n\n"
            f"Technical Signal: {tech.get('overall_signal', 'neutral')}\n"
            f"Timeframes:\n"
            + "\n".join(tf_blocks) + "\n\n"
        )

        if strategy_mode != "scalping":
            events = fund.get("events", [])
            events_summary = "; ".join([e.get("title", "") for e in events[:3]]) if events else "none"
            prompt += (
                f"Fundamental: {fund.get('direction_bias', 'neutral')} "
                f"(rate_spread:{fund.get('interest_rate_spread', 'N/A')}, "
                f"events:{events_summary})\n"
                f"Sentiment: {sent.get('overall_sentiment', 'neutral')} "
                f"(score:{sent.get('sentiment_score', 0):.2f})\n\n"
            )
        else:
            prompt += (
                f"Context: risk={fund.get('event_risk', 'low')}, "
                f"sentiment={sent.get('overall_sentiment', 'neutral')}\n\n"
            )

        prompt += "JSON: decision, confidence, entry, SL, TP, rationale."
        return prompt

    async def get_batched_trade_decisions(
        self,
        analyses: List[Dict[str, Any]],
        strategy_mode: str = "scalping",
        model_override: str = None,
        aggressiveness: str = "moderate",
        router: Optional[ModelRouter] = None,
    ) -> List[TradeDecision]:
        """Batch multiple pair analyses into a single AI prompt for efficiency."""
        if not self.api_key or len(analyses) == 0:
            return [self._fallback_decision(a, strategy_mode) for a in analyses]

        if len(analyses) == 1:
            return [await self.get_trade_decision(
                analyses[0], strategy_mode, model_override=model_override,
                aggressiveness=aggressiveness, router=router,
            )]

        prompt = self._build_batched_prompt(analyses, strategy_mode)
        payload = {
            "temperature": 0.15,
            "max_tokens": 512,  # Reduced from 1024 — batched JSON still compact
            "messages": [
                {"role": "system", "content": self._system_prompt(strategy_mode, aggressiveness) + "\n\nIMPORTANT: You are analyzing MULTIPLE currency pairs. Return a JSON array where each element is a decision object for the corresponding pair in the same order provided."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        candidates = await self._resolve_candidates(router, model_override)
        data, used_model = await self._post_with_failover(self._request_headers(), payload, candidates, router)

        content = data["choices"][0]["message"]["content"]
        decisions_list = self._parse_array(content)

        results = []
        for idx, analysis in enumerate(analyses):
            symbol = analysis.get("symbol", "EURUSD")
            if idx < len(decisions_list) and isinstance(decisions_list[idx], dict):
                d = decisions_list[idx]
                results.append(TradeDecision(
                    decision=normalize_decision(d.get("decision")),
                    confidence=float(d.get("confidence") or 0.0),
                    timeframe=d.get("timeframe", "M5" if strategy_mode == "scalping" else "H1"),
                    entry_price=float(d.get("entry_price") or 0.0),
                    stop_loss=float(d.get("stop_loss") or 0.0),
                    take_profit=float(d.get("take_profit") or 0.0),
                    position_size_pct=float(d.get("position_size_pct") or 1.0),
                    risk_reward=float(d.get("risk_reward") or 1.0),
                    rationale=d.get("rationale", "No rationale provided."),
                    symbol=symbol,
                    model_used=used_model,
                ))
            else:
                fb = self._fallback_decision(analysis, strategy_mode)
                fb.model_used = used_model
                results.append(fb)
        return results

    def _build_batched_prompt(self, analyses: List[Dict[str, Any]], strategy_mode: str) -> str:
        blocks = []
        for idx, analysis in enumerate(analyses):
            symbol = analysis.get("symbol", "EURUSD")
            tech = analysis.get("technical", {})
            fund = analysis.get("fundamental", {})
            sent = analysis.get("sentiment", {})
            tfs = tech.get("timeframes", {})

            tf_blocks = []
            for tf_name, tf_data in tfs.items():
                compressed = self._compress_timeframe(tf_data)
                tf_blocks.append(f"    {tf_name.upper()}: {compressed}")

            block = (
                f"[{idx + 1}] {symbol}: tech={tech.get('overall_signal', 'neutral')}\n"
                + "\n".join(tf_blocks) + "\n"
            )

            if strategy_mode != "scalping":
                block += (
                    f"  fund={fund.get('direction_bias', 'neutral')}, "
                    f"sent={sent.get('overall_sentiment', 'neutral')}\n\n"
                )
            else:
                block += (
                    f"  ctx: risk={fund.get('event_risk', 'low')}, "
                    f"sent={sent.get('overall_sentiment', 'neutral')}\n\n"
                )
            blocks.append(block)

        return (
            "Analyze these pairs. Return JSON array in SAME ORDER. "
            "Each element: decision, confidence, entry, SL, TP, rationale.\n\n"
            + "\n".join(blocks)
        )

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        s = (text or "").strip()
        if s.startswith("```"):
            s = s.strip("`")
            nl = s.find("\n")
            if nl != -1 and s[:nl].strip().lower() in ("json", ""):
                s = s[nl + 1:]
        return s.strip()

    def _extract_json(self, text: str) -> Any:
        """Best-effort JSON extraction from a possibly noisy model response.

        Handles markdown code fences and leading/trailing prose. Tries to parse
        the outermost array first, then the outermost object.
        """
        s = self._strip_code_fences(text)
        if not s:
            return {}
        a_start, a_end = s.find("["), s.rfind("]")
        o_start, o_end = s.find("{"), s.rfind("}")
        attempts = []
        if a_start != -1 and a_end > a_start:
            attempts.append(s[a_start:a_end + 1])
        if o_start != -1 and o_end > o_start:
            attempts.append(s[o_start:o_end + 1])
        for chunk in attempts:
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                continue
        return {}

    def _parse_object(self, content: str) -> Dict[str, Any]:
        """Parse a single-decision response into a dict (never raises)."""
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = self._extract_json(content)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {}
        return parsed if isinstance(parsed, dict) else {}

    def _parse_array(self, content: str) -> List[Any]:
        """Parse a batched response into a list of decision dicts (never raises)."""
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            parsed = self._extract_json(content)
        if isinstance(parsed, dict):
            parsed = parsed.get("decisions", parsed.get("results", []))
        return parsed if isinstance(parsed, list) else []

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
            model_used="fallback",
        )

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Tuple, List, Dict, Any
from app.celery_app import celery_app

logger = logging.getLogger("app.tasks.analysis")
from app.analysis.aggregator import AnalysisAggregator
from app.ai.openrouter_client import OpenRouterClient
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.services.news_service import NewsService
from app.services.notification_service import NotificationService
from app.services.settings_service import get_setting_bool, get_setting, get_setting_float, get_setting_int
from app.database import get_celery_session
from app import schemas
from app.enums import TradeDirection, TradeMode
from app.config import get_settings
from app.utils.time import utc_now
from sqlalchemy import select, func

settings = get_settings()


def _clean_numpy(obj):
    """Recursively convert numpy types to native Python types for JSON serialization."""
    import numpy as np
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _clean_numpy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_numpy(v) for v in obj]
    return obj


async def _trading_paused(strategy_mode: str, db) -> Tuple[bool, str]:
    """Check if trading should be paused (EOD, weekend, etc.)."""
    now = utc_now()

    eod_enabled = await get_setting_bool(db, "eod_close_enabled")
    if eod_enabled:
        no_entry_before = await get_setting(db, "eod_no_new_entries_before")
        try:
            hour, minute = map(int, no_entry_before.split(":"))
            cutoff = time(hour, minute)
            if now.time() >= cutoff:
                return True, f"Trading paused: no new entries after {no_entry_before} UTC (EOD)"
        except Exception:
            logger.warning("Failed to parse EOD time setting", exc_info=True)

    weekend_enabled = await get_setting_bool(db, "weekend_close_enabled")
    if weekend_enabled:
        weekend_close_str = await get_setting(db, "weekend_close_time_utc")
        weekend_resume_str = await get_setting(db, "weekend_resume_time_utc")
        try:
            wc_h, wc_m = map(int, weekend_close_str.split(":"))
            wr_h, wr_m = map(int, weekend_resume_str.split(":"))
            # Friday after close_time
            if now.weekday() == 4 and now.time() >= time(wc_h, wc_m):
                return True, f"Trading paused: weekend closure after {weekend_close_str} UTC Friday"
            # Saturday
            if now.weekday() == 5:
                return True, "Trading paused: weekend"
            # Sunday before resume_time
            if now.weekday() == 6 and now.time() < time(wr_h, wr_m):
                return True, f"Trading paused: weekend, resumes {weekend_resume_str} UTC Sunday"
        except Exception:
            logger.warning("Failed to parse weekend time settings", exc_info=True)

    return False, ""


async def _resolve_strategy_mode(db, aggregator: AnalysisAggregator) -> str:
    """Determine strategy mode: manual setting or auto-switch."""
    auto_switch = await get_setting_bool(db, "auto_strategy_switch_enabled")
    if not auto_switch:
        mode = await get_setting(db, "strategy_mode")
        return mode if mode in ("scalping", "day_trading", "swing") else "scalping"

    # Auto-switch logic based on volatility and session
    now = utc_now()
    hour = now.hour

    # Default to day_trading for London/NY overlap (high volatility)
    if 8 <= hour < 17:
        return "day_trading"
    # Scalping for early London / late NY
    if (hour >= 6 and hour < 8) or (hour >= 17 and hour < 20):
        return "scalping"
    # Swing for overnight / low volatility
    return "swing"


# Health tracking for system monitoring
_health_state = {
    "ai_available": True,
    "last_successful_analysis": None,
    "last_error": None,
    "consecutive_ai_failures": 0,
}


def get_health_state() -> dict:
    return dict(_health_state)


def _generate_rule_based_decision(analysis: Dict[str, Any], strategy_mode: str) -> Any:
    """Generate a trade decision using technical rules only (no AI).
    Used as fallback when AI is unavailable and fallback_strategy == 'rule_based'.
    """
    from app.ai.openrouter_client import TradeDecision
    tech = analysis.get("technical", {})
    tfs = tech.get("timeframes", {})
    symbol = analysis.get("symbol", "EURUSD")

    # Find the primary timeframe for this strategy
    if strategy_mode == "scalping":
        primary_tf = tfs.get("1m", {}) or tfs.get("5m", {})
    elif strategy_mode == "day_trading":
        primary_tf = tfs.get("15m", {}) or tfs.get("5m", {})
    else:
        primary_tf = tfs.get("1h", {}) or tfs.get("4h", {})

    ind = primary_tf.get("indicators", {})
    signal = primary_tf.get("signal", "neutral")
    confidence = primary_tf.get("confidence", 0.3)
    ema9 = ind.get("ema_9", 0)
    ema21 = ind.get("ema_21", 0)
    adx = ind.get("adx_14", 0)
    rsi = ind.get("rsi_14", 50)
    atr = ind.get("atr_14", 0)
    close = primary_tf.get("close") or ind.get("close", 1.0)
    support = primary_tf.get("support", close * 0.995)
    resistance = primary_tf.get("resistance", close * 1.005)

    # Rule-based decision logic
    decision = "HOLD"
    entry = close
    sl = 0.0
    tp = 0.0
    rationale = ""

    if adx >= 20 and ema9 > 0 and ema21 > 0:
        if ema9 > ema21 and signal == "bullish" and rsi < 70:
            decision = "BUY"
            sl = max(support, close - atr * 1.5)
            tp = min(resistance, close + atr * 2.5)
            rationale = f"Rule-based BUY: EMA9({ema9:.5f})>EMA21({ema21:.5f}), ADX={adx:.0f}, RSI={rsi:.0f}, ATR={atr:.5f}"
        elif ema9 < ema21 and signal == "bearish" and rsi > 30:
            decision = "SELL"
            sl = min(resistance, close + atr * 1.5)
            tp = max(support, close - atr * 2.5)
            rationale = f"Rule-based SELL: EMA9({ema9:.5f})<EMA21({ema21:.5f}), ADX={adx:.0f}, RSI={rsi:.0f}, ATR={atr:.5f}"
    else:
        rationale = f"Rule-based HOLD: ADX={adx:.0f} (<20 no trend), EMA alignment inconclusive"

    if not rationale:
        rationale = f"Rule-based {decision}: signal={signal}, confidence={confidence:.0%}"

    return TradeDecision(
        decision=decision,
        confidence=confidence,
        timeframe="M5" if strategy_mode == "scalping" else "H1",
        entry_price=round(entry, 5),
        stop_loss=round(sl, 5) if sl else round(entry * 0.998, 5),
        take_profit=round(tp, 5) if tp else round(entry * 1.002, 5),
        position_size_pct=1.0,
        risk_reward=round(abs(tp - entry) / max(abs(entry - sl), 0.00001), 2) if sl and tp else 1.0,
        rationale=rationale,
        model_used="rule_based",
        symbol=symbol,
    )


async def _memory_guard(db, vs, analysis, decision):
    """Soft entry guard using Qdrant retrieval of historically similar setups.

    Returns (ok, reason, context_note). Vetoes the entry only when enough
    same-direction past setups with recorded outcomes were poor; otherwise
    returns a short note for the decision rationale.
    """
    if decision.decision not in ("BUY", "SELL"):
        return True, "", ""
    if not await get_setting_bool(db, "memory_guard_enabled"):
        return True, "", ""
    try:
        similar = vs.search_similar(analysis.get("technical", {}), limit=20)
    except Exception:
        logger.warning("Memory guard: Qdrant search failed", exc_info=True)
        return True, "", ""
    same = [s for s in similar if s.get("decision") == decision.decision and s.get("outcome_pnl") is not None]
    if len(same) < 5:
        return True, "", ""
    wins = sum(1 for s in same if (s.get("outcome_pnl") or 0) > 0)
    win_rate = wins / len(same)
    avg_pnl = sum((s.get("outcome_pnl") or 0) for s in same) / len(same)
    ctx = f"Memory: {len(same)} similar {decision.decision} setups -> {win_rate:.0%} win, avg ${avg_pnl:.2f}"
    min_wr = await get_setting_float(db, "memory_guard_min_winrate") or 0.35
    if win_rate < min_wr and avg_pnl < 0:
        return False, f"Memory guard veto: similar {decision.decision} setups historically poor ({win_rate:.0%} win, avg ${avg_pnl:.2f})", ctx
    return True, "", ctx


@celery_app.task
def run_full_analysis():
    async def _analyze():
        async with get_celery_session()() as db:
            from app import models
            from app.services.websocket_broadcaster import broadcast_ai_decision, broadcast_trade_event
            aggregator = AnalysisAggregator()
            ai = OpenRouterClient()
            executor = ExecutionService()
            risk = RiskManager()
            news = NewsService()
            notifier = NotificationService()

            strategy_mode = await _resolve_strategy_mode(db, aggregator)

            # Check trading pause (EOD / weekend)
            paused, pause_reason = await _trading_paused(strategy_mode, db)
            if paused:
                return {"status": "paused", "reason": pause_reason}

            active_result = await db.execute(select(models.ActivePair).order_by(models.ActivePair.priority))
            active_pairs = active_result.scalars().all()

            if not active_pairs:
                active_pairs = [models.ActivePair(symbol="EURUSD", selection_mode="manual", priority=1)]

            manual_override = await get_setting_bool(db, "manual_override")
            results = []

            # Initialize Qdrant vector store
            from app.services.vector_store import VectorStore
            vs = VectorStore()

            # News-based trading halt per pair
            news_halt_enabled = await get_setting_bool(db, "news_halt_enabled")
            news_buffer_before = await get_setting_int(db, "news_halt_buffer_before_min") or 15
            news_buffer_after = await get_setting_int(db, "news_halt_buffer_after_min") or 30

            # Gather all analyses first
            analyses: List[Dict[str, Any]] = []
            for pair in active_pairs:
                symbol = pair.symbol
                analysis = await aggregator.gather_all(symbol, strategy_mode=strategy_mode, db=db)
                analysis["symbol"] = symbol
                analyses.append(analysis)

            # Check news halt for each pair
            allowed_analyses = []
            for analysis in analyses:
                symbol = analysis["symbol"]
                if news_halt_enabled:
                    news_halted, news_reason = await news.is_trading_halted(
                        symbol,
                        buffer_minutes_before=news_buffer_before,
                        buffer_minutes_after=news_buffer_after,
                    )
                else:
                    news_halted = False
                    news_reason = ""
                if news_halted:
                    results.append({"symbol": symbol, "decision": "HOLD", "confidence": 0.0, "reason": news_reason})
                    # Broadcast as HOLD with news reason
                    db_decision = models.AIDecision(
                        symbol=symbol,
                        decision="HOLD",
                        confidence=0.0,
                        rationale=news_reason,
                        model_used="",
                        provider=settings.DATA_PROVIDER.value,
                    )
                    db.add(db_decision)
                    await db.commit()
                    await db.refresh(db_decision)
                    await broadcast_ai_decision({
                        "id": db_decision.id,
                        "symbol": symbol,
                        "decision": "HOLD",
                        "confidence": 0.0,
                        "rationale": news_reason,
                        "manual_override": manual_override,
                        "strategy_mode": strategy_mode,
                    })
                else:
                    allowed_analyses.append(analysis)

            # ------------------------------------------------------------------
            # XGBoost Entry Gate — skip LLM if predicted quality is too low
            # ------------------------------------------------------------------
            entry_gate_enabled = await get_setting_bool(db, "entry_gate_enabled")
            entry_gate_threshold = await get_setting_float(db, "entry_gate_threshold") or 0.40
            if entry_gate_enabled:
                from app.services.feature_store import FeatureStore
                from app.services.ml.entry_model import EntryQualityModel
                entry_model = EntryQualityModel()
                filtered_analyses = []
                for analysis in allowed_analyses:
                    symbol = analysis["symbol"]
                    features = FeatureStore.compute_entry_features(analysis)
                    score = entry_model.predict(features)
                    if score is not None and score < entry_gate_threshold:
                        results.append({
                            "symbol": symbol,
                            "decision": "HOLD",
                            "confidence": 0.0,
                            "reason": f"Entry gate blocked (score={score:.2f} < {entry_gate_threshold})",
                        })
                        db_decision = models.AIDecision(
                            symbol=symbol,
                            decision="HOLD",
                            confidence=0.0,
                            rationale=f"Entry gate blocked (score={score:.2f} < {entry_gate_threshold})",
                            model_used="xgb_entry_gate",
                            provider=settings.DATA_PROVIDER.value,
                        )
                        db.add(db_decision)
                        await db.commit()
                        await db.refresh(db_decision)
                        await broadcast_ai_decision({
                            "id": db_decision.id,
                            "symbol": symbol,
                            "decision": "HOLD",
                            "confidence": 0.0,
                            "rationale": f"Entry gate blocked (score={score:.2f} < {entry_gate_threshold})",
                            "manual_override": manual_override,
                            "strategy_mode": strategy_mode,
                        })
                        logger.info("Entry gate blocked %s (score=%.2f)", symbol, score)
                    else:
                        filtered_analyses.append(analysis)
                allowed_analyses = filtered_analyses

            # Use batched AI prompt if enabled and multiple pairs
            batched_enabled = await get_setting_bool(db, "batched_ai_enabled")
            ai_model = await get_setting(db, "ai_model") or settings.OPENROUTER_MODEL
            aggressiveness = await get_setting(db, "trade_aggressiveness") or "moderate"

            # Build the model router (round-robin across free models + failover)
            from app.ai.model_router import ModelRouter, parse_pool
            rotation_enabled = await get_setting_bool(db, "ai_model_rotation_enabled")
            paid_fallback_enabled = await get_setting_bool(db, "ai_paid_fallback_enabled")
            paid_fallback = (await get_setting(db, "ai_paid_fallback_model")) if paid_fallback_enabled else None
            router = ModelRouter(
                free_pool=parse_pool(await get_setting(db, "ai_model_pool")),
                paid_fallback=paid_fallback,
                cooldown_sec=await get_setting_int(db, "ai_model_cooldown_sec") or 120,
                rotation_enabled=rotation_enabled,
            )
            decisions_map = {}
            ai_error_occurred = False
            ai_error_message = ""

            # ------------------------------------------------------------------
            # Resolve model suite (used by both v1 and v2 engine paths)
            # ------------------------------------------------------------------
            from app.ai.suites import resolve_models
            suite = await get_setting(db, "model_suite") or "free"
            overrides = {
                "technical": await get_setting(db, "model_technical"),
                "fundamental": await get_setting(db, "model_fundamental"),
                "sentiment": await get_setting(db, "model_sentiment"),
                "macro": await get_setting(db, "model_macro"),
                "lead": await get_setting(db, "model_lead"),
                "verifier": await get_setting(db, "model_verifier"),
            }
            models_map = resolve_models(suite, overrides)

            # ------------------------------------------------------------------
            # v2 multi-agent team engine (behind feature flag)
            # ------------------------------------------------------------------
            engine_version = await get_setting(db, "decision_engine_version") or "v1"
            v2_results = {}  # symbol -> v2 dict (for DB storage)

            if engine_version == "v2":
                from app.ai.team.orchestrator import TeamDecisionEngine
                team = TeamDecisionEngine(
                    technical_model=models_map.get("technical"),
                    fundamental_model=models_map.get("fundamental"),
                    sentiment_model=models_map.get("sentiment"),
                    macro_model=models_map.get("macro"),
                    lead_model=models_map.get("lead"),
                    verifier_model=models_map.get("verifier"),
                    verifier_enabled=await get_setting_bool(db, "verifier_enabled"),
                    verifier_can_veto=await get_setting_bool(db, "verifier_can_veto"),
                    analyst_parallelism=await get_setting_bool(db, "analyst_parallelism"),
                )
                try:
                    for analysis in allowed_analyses:
                        symbol = analysis["symbol"]
                        v2_result = await team.decide(symbol, strategy_mode, analysis)
                        v2_results[symbol] = v2_result
                        # Wrap v2 dict in a TradeDecision for downstream compatibility
                        from app.ai.openrouter_client import TradeDecision
                        decisions_map[symbol] = TradeDecision(
                            decision=v2_result["decision"],
                            confidence=v2_result["confidence"],
                            timeframe=v2_result["timeframe"],
                            entry_price=v2_result.get("entry_price", 0.0),
                            stop_loss=v2_result.get("stop_loss", 0.0),
                            take_profit=v2_result.get("take_profit", 0.0),
                            position_size_pct=v2_result["position_size_pct"],
                            risk_reward=v2_result["risk_reward"],
                            rationale=v2_result["rationale"],
                            symbol=symbol,
                            model_used=v2_result.get("lead_model", ""),
                        )
                except Exception as e:
                    logger.error("v2 TeamDecisionEngine failed: %s", e, exc_info=True)
                    ai_error_occurred = True
                    ai_error_message = str(e)
                    fallback_strategy = await get_setting(db, "ai_fallback_strategy") or "hold"
                    for analysis in allowed_analyses:
                        symbol = analysis["symbol"]
                        if fallback_strategy == "rule_based":
                            decision = _generate_rule_based_decision(analysis, strategy_mode)
                        else:
                            decision = ai._fallback_decision(analysis, strategy_mode)
                        decision.rationale = f"[v2 TEAM UNAVAILABLE: {ai_error_message[:120]}] {decision.rationale}"
                        decisions_map[symbol] = decision
            else:
                # v1 single-LLM path — uses the resolved lead model from the suite
                v1_model = models_map.get("lead") or ai_model
                try:
                    if batched_enabled and len(allowed_analyses) > 1:
                        batched_decisions = await ai.get_batched_trade_decisions(
                            allowed_analyses, strategy_mode=strategy_mode,
                            model_override=v1_model, aggressiveness=aggressiveness,
                            router=router,
                        )
                        for analysis, decision in zip(allowed_analyses, batched_decisions):
                            decisions_map[analysis["symbol"]] = decision
                    else:
                        for analysis in allowed_analyses:
                            decision = await ai.get_trade_decision(
                                analysis, strategy_mode=strategy_mode,
                                model_override=v1_model, aggressiveness=aggressiveness,
                                router=router,
                            )
                            decisions_map[analysis["symbol"]] = decision
                except Exception as e:
                    logger.error("AI decision failed: %s", e, exc_info=True)
                    ai_error_occurred = True
                    ai_error_message = str(e)
                    fallback_strategy = await get_setting(db, "ai_fallback_strategy") or "hold"
                    for analysis in allowed_analyses:
                        symbol = analysis["symbol"]
                        if fallback_strategy == "rule_based":
                            decision = _generate_rule_based_decision(analysis, strategy_mode)
                        else:
                            decision = ai._fallback_decision(analysis, strategy_mode)
                        decision.rationale = f"[AI UNAVAILABLE: {ai_error_message[:120]}] {decision.rationale}"
                        decisions_map[symbol] = decision

            # Update health state
            _health_state["ai_available"] = not ai_error_occurred
            _health_state["last_error"] = ai_error_message if ai_error_occurred else None
            if not ai_error_occurred:
                _health_state["last_successful_analysis"] = utc_now().isoformat()
                _health_state["consecutive_ai_failures"] = 0
            else:
                _health_state["consecutive_ai_failures"] += 1

            # Notify on consecutive AI failures
            if _health_state["consecutive_ai_failures"] >= 3:
                try:
                    await notifier.send_system_alert(
                        db,
                        title="AI Service Unavailable",
                        message=f"OpenRouter API has failed {_health_state['consecutive_ai_failures']} consecutive times. "
                                f"Last error: {ai_error_message[:200]}. "
                                f"Fallback strategy: {fallback_strategy if ai_error_occurred else 'N/A'}. "
                                f"Check OpenRouter credits at https://openrouter.ai/keys",
                        severity="critical",
                    )
                except Exception:
                    logger.warning("Failed to send system alert notification", exc_info=True)

            # Process decisions
            for analysis in allowed_analyses:
                symbol = analysis["symbol"]
                decision = decisions_map[symbol]

                # Detect market regime for this symbol/timeframe
                from app.services.regime_detector import RegimeDetector
                regime_info = RegimeDetector.detect(
                    analysis.get("technical", {}), symbol=symbol
                )

                db_decision = models.AIDecision(
                    symbol=symbol,
                    decision=decision.decision,
                    confidence=decision.confidence,
                    timeframe=decision.timeframe,
                    entry_price=decision.entry_price,
                    stop_loss=decision.stop_loss,
                    take_profit=decision.take_profit,
                    position_size_pct=decision.position_size_pct,
                    risk_reward=decision.risk_reward,
                    rationale=decision.rationale,
                    technical_snapshot=_clean_numpy(analysis.get("technical")),
                    fundamental_snapshot=_clean_numpy(analysis.get("fundamental")),
                    sentiment_snapshot=_clean_numpy(analysis.get("sentiment")),
                    model_used=getattr(decision, "model_used", "") or ai_model,
                    provider=settings.DATA_PROVIDER.value,
                    engine_version=engine_version,
                    # v2 fields
                    analyst_opinions=_clean_numpy(v2_results.get(symbol, {}).get("analyst_opinions")),
                    lead_model=v2_results.get(symbol, {}).get("lead_model"),
                    verifier_model=v2_results.get(symbol, {}).get("verifier_model"),
                    verifier_verdict=v2_results.get(symbol, {}).get("verifier_verdict"),
                    regime=_clean_numpy({
                        "strategy_mode": strategy_mode,
                        "session": analysis.get("session"),
                        "detected": regime_info["regime"],
                        "regime_confidence": regime_info["confidence"],
                        "adx": regime_info["adx"],
                        "bb_width_pct": regime_info["bb_width_pct"],
                        "atr_pct": regime_info["atr_pct"],
                    }),
                    daily_bias=_clean_numpy(v2_results.get(symbol, {}).get("daily_bias")),
                )
                db.add(db_decision)
                await db.commit()
                await db.refresh(db_decision)

                # Persist regime label to market_regimes table
                try:
                    mr = models.MarketRegime(
                        symbol=symbol,
                        timeframe=decision.timeframe or "1h",
                        regime=regime_info["regime"],
                        adx=regime_info["adx"],
                        bb_width_pct=regime_info["bb_width_pct"],
                        atr_pct=regime_info["atr_pct"],
                        confidence=regime_info["confidence"],
                    )
                    db.add(mr)
                    await db.commit()
                except Exception:
                    logger.warning("Failed to insert MarketRegime for %s", symbol, exc_info=True)
                    await db.rollback()

                # Store market state snapshot to Qdrant vector DB + SQL table
                point_id = f"{db_decision.id}"
                try:
                    vs.upsert_snapshot(
                        point_id=point_id,
                        snapshot=analysis.get("technical", {}),
                        payload={
                            "symbol": symbol,
                            "decision": decision.decision,
                            "confidence": decision.confidence,
                            "strategy_mode": strategy_mode,
                            "timestamp": utc_now().isoformat(),
                        },
                    )
                except Exception:
                    logger.warning("Failed to upsert Qdrant snapshot for decision %s", db_decision.id, exc_info=True)

                # Persist snapshot metadata in SQL for audit + reporting
                try:
                    mss = models.MarketStateSnapshot(
                        symbol=symbol,
                        strategy_mode=strategy_mode,
                        decision=decision.decision,
                        confidence=decision.confidence,
                        qdrant_point_id=point_id,
                    )
                    db.add(mss)
                    await db.commit()
                except Exception:
                    logger.warning("Failed to insert MarketStateSnapshot for decision %s", db_decision.id, exc_info=True)
                    await db.rollback()

                # Back-link the Qdrant point ID to the AIDecision record
                if hasattr(db_decision, "qdrant_point_id"):
                    try:
                        db_decision.qdrant_point_id = point_id
                        await db.commit()
                    except Exception:
                        logger.warning("Failed to set qdrant_point_id on AIDecision %s", db_decision.id, exc_info=True)
                        await db.rollback()

                # Broadcast AI decision to all connected clients
                await broadcast_ai_decision({
                    "id": db_decision.id,
                    "symbol": symbol,
                    "decision": decision.decision,
                    "confidence": decision.confidence,
                    "timeframe": decision.timeframe,
                    "entry_price": decision.entry_price,
                    "stop_loss": decision.stop_loss,
                    "take_profit": decision.take_profit,
                    "position_size_pct": decision.position_size_pct,
                    "risk_reward": decision.risk_reward,
                    "rationale": decision.rationale,
                    "manual_override": manual_override,
                    "strategy_mode": strategy_mode,
                })

                if decision.decision not in ("BUY", "SELL"):
                    logger.info("[AUDIT] %s: AI=HOLD(%.2f) — no trade signal", symbol, decision.confidence)

                    # When fallback strategy is rule_based, try rule-based decision as override
                    fallback_strategy = await get_setting(db, "ai_fallback_strategy") or "hold"
                    if fallback_strategy == "rule_based" and not manual_override:
                        rule_decision = _generate_rule_based_decision(analysis, strategy_mode)
                        if rule_decision.decision in ("BUY", "SELL"):
                            logger.info(
                                "[AUDIT] %s: AI=HOLD → RULE_OVERRIDE=%s(%.2f)",
                                symbol, rule_decision.decision, rule_decision.confidence,
                            )
                            decision = rule_decision
                            decision.rationale = f"[RULE OVERRIDE — AI returned HOLD] {decision.rationale}"

                if decision.decision in ("BUY", "SELL") and not manual_override:
                    ok, reason = await risk.validate_ai_decision(db, decision)
                    if ok:
                        # Extract ATR from smallest timeframe analysis
                        tech = analysis.get("technical", {})
                        tfs = tech.get("timeframes", {})
                        first_tf = next(iter(tfs.values()), {})
                        ind = first_tf.get("indicators", {})
                        atr = ind.get("atr_14", 0.0)

                        # 1. ATR-based SL/TP validation
                        ok2, reason2 = await risk.validate_sl_tp_atr(
                            db, decision.entry_price, decision.stop_loss, decision.take_profit, atr
                        )
                        if not ok2:
                            ok = False
                            reason = reason2

                        # 2. Spread efficiency filter
                        if ok:
                            ok3, reason3 = await risk.validate_spread(db, symbol, atr)
                            if not ok3:
                                ok = False
                                reason = reason3

                        # 3. Correlation guard
                        if ok:
                            ok4, reason4 = await risk.validate_correlation(db, symbol)
                            if not ok4:
                                ok = False
                                reason = reason4

                        # Historical memory guard (Qdrant retrieval of similar setups)
                        if ok:
                            mem_ok, mem_reason, mem_ctx = await _memory_guard(db, vs, analysis, decision)
                            if mem_ctx:
                                decision.rationale = f"{decision.rationale} | {mem_ctx}"
                            if not mem_ok:
                                ok = False
                                reason = mem_reason

                        if ok:
                            equity = await risk._get_equity(db)
                            position_size = risk.calculate_position_size(
                                equity, decision.position_size_pct,
                                decision.entry_price, decision.stop_loss,
                                symbol,
                            )

                            # 4. Drawdown-based position size reduction
                            position_size, dd_reason = await risk.apply_drawdown_reduction(db, position_size)
                            if position_size <= 0:
                                ok = False
                                reason = dd_reason

                        if ok:
                            # Calculate trailing stop distance from ATR
                            from app.services.settings_service import get_setting_float
                            trailing_atr_mult = await get_setting_float(db, "trailing_stop_distance_atr")
                            trailing_distance = atr * trailing_atr_mult if atr and trailing_atr_mult else None

                            trade_in = schemas.TradeCreate(
                                symbol=symbol,
                                direction=TradeDirection(decision.decision.lower()),
                                entry_price=decision.entry_price,
                                stop_loss=decision.stop_loss,
                                take_profit=decision.take_profit,
                                risk_pct=decision.position_size_pct,
                                mode=TradeMode.PAPER,
                                provider=settings.DATA_PROVIDER,
                                ai_decision_id=db_decision.id,
                                rationale=decision.rationale,
                            )
                            trade = await executor.execute_trade(
                                db, trade_in, position_size=position_size,
                                strategy_mode=strategy_mode, trailing_distance=trailing_distance
                            )
                            await broadcast_trade_event("executed", {
                                "id": trade.id,
                                "symbol": trade.symbol,
                                "direction": trade.direction,
                                "entry_price": trade.entry_price,
                                "stop_loss": trade.stop_loss,
                                "take_profit": trade.take_profit,
                                "mode": trade.mode,
                                "position_size": trade.position_size,
                                "ai_decision_id": trade.ai_decision_id,
                                "strategy_mode": strategy_mode,
                            })

                            # Send notification
                            try:
                                await notifier.send_trade_opened(
                                    db,
                                    symbol=trade.symbol,
                                    direction=trade.direction.upper(),
                                    entry_price=trade.entry_price,
                                    stop_loss=trade.stop_loss,
                                    take_profit=trade.take_profit,
                                    position_size=trade.position_size,
                                    strategy_mode=strategy_mode,
                                    rationale=decision.rationale,
                                )
                            except Exception:
                                logger.warning("Failed to send trade opened notification", exc_info=True)

                            # Audit log: trade executed
                            logger.info(
                                "[AUDIT] %s: AI=%s(%.2f) → Risk=OK → SL/TP=OK → Spread=OK → Corr=OK → DD=OK → EXECUTED(%.3f lots, %s)",
                                symbol, decision.decision, decision.confidence,
                                trade.position_size, strategy_mode,
                            )
                        else:
                            decision.decision = "HOLD"
                            decision.rationale += f" [RISK BLOCKED: {reason}]"
                            db_decision.decision = "HOLD"
                            db_decision.rationale = decision.rationale
                            await db.commit()

                            # Audit log: blocked by risk checks
                            logger.info(
                                "[AUDIT] %s: AI=%s(%.2f) → Risk=OK → BLOCKED: %s",
                                symbol, decision.decision, decision.confidence, reason,
                            )
                            await broadcast_ai_decision({
                                "id": db_decision.id,
                                "symbol": symbol,
                                "decision": "HOLD",
                                "confidence": decision.confidence,
                                "rationale": decision.rationale,
                                "manual_override": manual_override,
                                "strategy_mode": strategy_mode,
                            })
                    else:
                        decision.decision = "HOLD"
                        decision.rationale += f" [RISK BLOCKED: {reason}]"
                        db_decision.decision = "HOLD"
                        db_decision.rationale = decision.rationale
                        await db.commit()

                        # Audit log: blocked by initial risk validation
                        logger.info(
                            "[AUDIT] %s: AI=%s(%.2f) → BLOCKED: %s",
                            symbol, decision.decision, decision.confidence, reason,
                        )
                        await broadcast_ai_decision({
                            "id": db_decision.id,
                            "symbol": symbol,
                            "decision": "HOLD",
                            "confidence": decision.confidence,
                            "rationale": decision.rationale,
                            "manual_override": manual_override,
                            "strategy_mode": strategy_mode,
                        })

                results.append({
                    "symbol": symbol,
                    "decision": str(decision.decision),
                    "confidence": float(decision.confidence),
                })

            return results

    return asyncio.run(_analyze())


@celery_app.task
def auto_select_pairs():
    async def _select():
        async with get_celery_session()() as db:
            from app import models
            strategy_mode = await _resolve_strategy_mode(db, AnalysisAggregator())

            result = await db.execute(select(models.ActivePair).where(models.ActivePair.selection_mode == "auto"))
            auto_pairs = result.scalars().all()
            if not auto_pairs:
                return {"detail": "No auto-selection pairs configured"}

            aggregator = AnalysisAggregator()
            available = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]
            scored = []
            for sym in available:
                analysis = await aggregator.gather_all(sym, strategy_mode=strategy_mode, db=db)
                score = aggregator._score_pair(analysis)
                scored.append((sym, score))

            scored.sort(key=lambda x: abs(x[1]), reverse=True)
            top = scored[:len(auto_pairs)]

            for idx, pair in enumerate(auto_pairs):
                if idx < len(top):
                    pair.symbol = top[idx][0]

            await db.commit()
            return {"selected": [s for s, _ in top], "strategy_mode": strategy_mode}

    return asyncio.run(_select())


@celery_app.task
def record_hourly_performance():
    async def _record():
        async with get_celery_session()() as db:
            from app import models
            now = utc_now()
            hour = now.hour
            strategy_mode = await get_setting(db, "strategy_mode") or "scalping"

            # Get today's closed trades
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            result = await db.execute(
                select(models.Trade).where(
                    models.Trade.status == models.TradeStatus.CLOSED,
                    models.Trade.close_time >= start_of_day,
                )
            )
            trades = result.scalars().all()

            for trade in trades:
                sym = trade.symbol
                perf_result = await db.execute(
                    select(models.PairPerformanceByHour).where(
                        models.PairPerformanceByHour.symbol == sym,
                        models.PairPerformanceByHour.hour_utc == hour,
                        models.PairPerformanceByHour.strategy_mode == strategy_mode,
                    )
                )
                perf = perf_result.scalar_one_or_none()
                if not perf:
                    perf = models.PairPerformanceByHour(
                        symbol=sym,
                        hour_utc=hour,
                        strategy_mode=strategy_mode,
                        total_trades=0,
                        winning_trades=0,
                        avg_pnl=0.0,
                    )
                    db.add(perf)

                perf.total_trades += 1
                if (trade.pnl or 0) > 0:
                    perf.winning_trades += 1
                # Update rolling average PnL
                old_avg = perf.avg_pnl or 0.0
                perf.avg_pnl = old_avg + ((trade.pnl or 0) - old_avg) / perf.total_trades
                perf.updated_at = now

            await db.commit()
            return {"recorded": len(trades), "hour": hour}

    return asyncio.run(_record())


@celery_app.task
def compute_pattern_priors():
    """Nightly task: compute pattern priors from closed trades and cache in Redis."""
    async def _compute():
        async with get_celery_session()() as db:
            from sqlalchemy import select
            from app import models
            from app.services.pattern_extractor import PatternExtractor

            result = await db.execute(
                select(models.Trade).where(models.Trade.status == models.TradeStatus.CLOSED)
                .order_by(models.Trade.close_time.desc())
                .limit(500)
            )
            trades = result.scalars().all()

            trade_dicts = []
            for t in trades:
                # Determine session from open_time
                from datetime import timezone
                hour = t.open_time.hour if t.open_time else 12
                session = "london" if 7 <= hour < 16 else "ny" if 12 <= hour < 21 else "asia"
                trade_dicts.append({
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "pnl": t.pnl or 0,
                    "regime": t.regime or "unknown",
                    "session": session,
                    "pattern_tags": t.pattern_tags or [],
                })

            extractor = PatternExtractor()
            priors = extractor.compute_pattern_priors(trade_dicts)
            await extractor.cache_priors(priors)
            logger.info("compute_pattern_priors: cached priors for %d trades", len(trade_dicts))

    asyncio.run(_compute())


@celery_app.task
def update_model_performance():
    """Hourly task: populate ModelPerformance table from recent decisions."""
    async def _update():
        async with get_celery_session()() as db:
            from sqlalchemy import select, func
            from datetime import datetime, timedelta, timezone
            from app import models

            since = datetime.now(timezone.utc) - timedelta(hours=24)
            result = await db.execute(
                select(models.AIDecision)
                .where(models.AIDecision.created_at >= since)
                .where(models.AIDecision.outcome.isnot(None))
            )
            decisions = result.scalars().all()

            # Group by model_used
            by_model = {}
            for d in decisions:
                model = d.model_used or "unknown"
                by_model.setdefault(model, []).append(d)

            for model, decs in by_model.items():
                wins = sum(1 for d in decs if d.outcome == "win")
                losses = sum(1 for d in decs if d.outcome == "loss")
                total = wins + losses
                if total == 0:
                    continue
                win_rate = wins / total
                avg_confidence = sum(d.confidence or 0 for d in decs) / len(decs)

                mp = models.ModelPerformance(
                    model_name=model,
                    version="1.0.0",
                    timeframe="mixed",
                    win_rate=win_rate,
                    avg_return=sum(d.realized_return or 0 for d in decs) / total,
                    total_trades=total,
                    avg_confidence=avg_confidence,
                    computed_at=datetime.now(timezone.utc),
                )
                db.add(mp)
            await db.commit()
            logger.info("update_model_performance: updated %d models", len(by_model))

    asyncio.run(_update())


@celery_app.task
def train_entry_model():
    """On-demand / scheduled task: retrain XGBoost entry quality model."""
    async def _train():
        async with get_celery_session()() as db:
            from sqlalchemy import select
            from datetime import datetime, timedelta, timezone
            from app import models
            from app.services.feature_store import FeatureStore
            from app.services.ml.entry_model import EntryQualityModel

            # Fetch closed trades with their associated decisions
            since = datetime.now(timezone.utc) - timedelta(days=90)
            result = await db.execute(
                select(models.Trade)
                .where(models.Trade.status == models.TradeStatus.CLOSED)
                .where(models.Trade.close_time >= since)
                .where(models.Trade.ai_decision_id.isnot(None))
                .limit(2000)
            )
            trades = result.scalars().all()

            decisions_data = []
            for t in trades:
                # Fetch the decision snapshot
                d_result = await db.execute(
                    select(models.AIDecision)
                    .where(models.AIDecision.id == t.ai_decision_id)
                )
                decision = d_result.scalar_one_or_none()
                if not decision:
                    continue
                # Reconstruct features from stored snapshots
                analysis = {
                    "technical": decision.technical_snapshot or {},
                    "fundamental": decision.fundamental_snapshot or {},
                    "sentiment": decision.sentiment_snapshot or {},
                    "macro": decision.macro_snapshot or {},
                }
                features = FeatureStore.compute_entry_features(analysis)
                label = 1 if (t.pnl or 0) > 0 else 0
                decisions_data.append({
                    "features": features,
                    "label": label,
                    "symbol": t.symbol,
                    "direction": t.direction,
                })

            if len(decisions_data) < 50:
                logger.warning("train_entry_model: insufficient data (%d samples), skipping", len(decisions_data))
                return

            df = FeatureStore.export_training_set(decisions_data)
            model = EntryQualityModel()
            metrics = model.train(df)
            logger.info("train_entry_model: retrained — test_auc=%.3f", metrics.get("test_auc", 0))

    asyncio.run(_train())


@celery_app.task
def rolling_backtest_30d():
    """Nightly task: run rolling 30-day backtest on recent closed trades."""
    async def _run():
        async with get_celery_session()() as db:
            from sqlalchemy import select
            from datetime import datetime, timedelta, timezone
            from app import models
            from app.backtest.walk_forward import WalkForwardTester
            from app.backtest.monte_carlo import MonteCarloSimulator
            from app.backtest.regime_tester import RegimeBacktester

            since = datetime.now(timezone.utc) - timedelta(days=90)
            result = await db.execute(
                select(models.Trade)
                .where(models.Trade.status == models.TradeStatus.CLOSED)
                .where(models.Trade.close_time >= since)
                .order_by(models.Trade.close_time)
            )
            trades = result.scalars().all()

            if len(trades) < 30:
                logger.info("rolling_backtest_30d: insufficient trades (%d), skipping", len(trades))
                return

            # Walk-forward
            decisions = [
                {
                    "timestamp": t.close_time,
                    "pnl": t.pnl or 0,
                    "direction": t.direction,
                }
                for t in trades
            ]
            wf_results = WalkForwardTester.run(decisions, train_months=2, test_months=1)
            for r in wf_results:
                br = models.BacktestRun(
                    symbol="MULTI",
                    start_date=datetime.fromisoformat(r["window_start"].replace("Z", "+00:00")),
                    end_date=datetime.fromisoformat(r["window_end"].replace("Z", "+00:00")),
                    total_trades=r["test_samples"],
                    win_rate=r["win_rate"],
                    profit_factor=r["profit_factor"],
                    sharpe_ratio=r["sharpe"],
                    max_drawdown_pct=r["max_drawdown"],
                    backtest_type="walk_forward",
                )
                db.add(br)

            # Monte Carlo on daily returns
            daily_pnls = {}
            for t in trades:
                day = t.close_time.date()
                daily_pnls[day] = daily_pnls.get(day, 0) + (t.pnl or 0)
            mc_result = MonteCarloSimulator.run(
                list(daily_pnls.values()), n_runs=5000, initial_equity=1000, ruin_threshold=700
            )
            if mc_result:
                br = models.BacktestRun(
                    symbol="MULTI",
                    start_date=since,
                    end_date=datetime.now(timezone.utc),
                    total_trades=len(trades),
                    profit_factor=mc_result.get("median_profit_factor", 0),
                    max_drawdown_pct=mc_result.get("median_max_dd_pct", 0),
                    backtest_type="monte_carlo",
                    mc_ruin_probability=mc_result.get("ruin_probability"),
                    mc_median_dd_pct=mc_result.get("median_max_dd_pct"),
                )
                db.add(br)

            # Regime backtest
            regime_trades = [{"regime": t.regime or "unknown", "pnl": t.pnl or 0} for t in trades]
            regime_result = RegimeBacktester.run(regime_trades)
            for regime, stats in regime_result.items():
                br = models.BacktestRun(
                    symbol="MULTI",
                    start_date=since,
                    end_date=datetime.now(timezone.utc),
                    total_trades=stats["count"],
                    win_rate=stats["win_rate"],
                    profit_factor=stats["profit_factor"],
                    max_drawdown_pct=stats["max_drawdown"],
                    backtest_type="regime",
                    regime=regime,
                )
                db.add(br)

            await db.commit()
            logger.info("rolling_backtest_30d: %d WF, MC ruin=%.2f, %d regimes",
                        len(wf_results), mc_result.get("ruin_probability", 0), len(regime_result))

    asyncio.run(_run())


@celery_app.task
def daily_kpi_snapshot():
    """Daily task: snapshot paper trading KPIs to database for trend tracking."""
    async def _snapshot():
        async with get_celery_session()() as db:
            from app.services.paper_trading_monitor import PaperTradingMonitor
            from app import models
            from datetime import datetime, timezone

            report = await PaperTradingMonitor.compute_report(db, days=7)
            snapshot = models.ModelPerformance(
                model_name="paper_trading_kpi",
                version="v1.5.0",
                timeframe="daily",
                win_rate=report.get("win_rate", 0),
                avg_return=report.get("net_pnl", 0),
                total_trades=report.get("total_trades", 0),
                avg_confidence=report.get("avg_exit_quality", 0),
                computed_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)
            await db.commit()
            logger.info("daily_kpi_snapshot: win_rate=%.2f trades=%d",
                        report.get("win_rate", 0), report.get("total_trades", 0))

    asyncio.run(_snapshot())

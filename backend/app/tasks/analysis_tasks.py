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


async def _should_run_analysis(r, symbol: str, current_price: float, threshold: float = 0.00005) -> bool:
    """Skip analysis if price hasn't moved meaningfully since last run.

    Returns True if we should proceed with analysis, False if price is flat.
    Falls back to True (run analysis) if Redis is unavailable.
    Threshold: 0.005% — minimal gate to skip truly identical prices (broker returning same tick).
    """
    try:
        last = await r.get(f"last_analysis_price:{symbol}")
        if not last:
            return True
        last_price = float(last)
        if last_price == 0:
            return True
        change = abs(current_price - last_price) / last_price
        return change >= threshold
    except Exception:
        return True


async def _store_last_price(r, symbol: str, price: float, ttl: int = 3600):
    """Store current price in Redis after analysis. TTL = 1h (covers 2 analysis cycles)."""
    try:
        await r.setex(f"last_analysis_price:{symbol}", ttl, str(price))
    except Exception:
        pass


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

    # Rule-based decision logic — relaxed thresholds for paper trading
    decision = "HOLD"
    entry = close
    sl = 0.0
    tp = 0.0
    rationale = ""

    # Ensure ATR is valid; fall back to a small fraction of price
    if not atr or atr <= 0:
        atr = close * 0.001  # 0.1% of price as fallback

    # Lower ADX threshold for scalping (trends are weaker on 1m/5m)
    adx_threshold = 15 if strategy_mode == "scalping" else 20

    if adx >= adx_threshold and ema9 > 0 and ema21 > 0:
        if ema9 > ema21 and signal in ("bullish", "neutral") and rsi < 75:
            decision = "BUY"
            sl = close - atr * 1.5
            tp = close + atr * 2.5
            # Only use support/resistance if they provide wider stops
            if support > 0 and support < sl:
                sl = support  # tighter SL at support
            if resistance > 0 and resistance > tp:
                tp = resistance  # wider TP at resistance
            rationale = f"Rule-based BUY: EMA9({ema9:.5f})>EMA21({ema21:.5f}), ADX={adx:.0f}, RSI={rsi:.0f}, ATR={atr:.5f}"
        elif ema9 < ema21 and signal in ("bearish", "neutral") and rsi > 25:
            decision = "SELL"
            sl = close + atr * 1.5
            tp = close - atr * 2.5
            # Only use support/resistance if they provide wider stops
            if resistance > 0 and resistance < sl:
                sl = resistance  # tighter SL at resistance
            if support > 0 and support < tp:
                tp = support  # wider TP at support
            rationale = f"Rule-based SELL: EMA9({ema9:.5f})<EMA21({ema21:.5f}), ADX={adx:.0f}, RSI={rsi:.0f}, ATR={atr:.5f}"
    else:
        rationale = f"Rule-based HOLD: ADX={adx:.0f} (<{adx_threshold} no trend), EMA alignment inconclusive"

    if not rationale:
        rationale = f"Rule-based {decision}: signal={signal}, confidence={confidence:.0%}"

    # For rule-based overrides, ensure minimum confidence and R:R
    if decision in ("BUY", "SELL"):
        # Set a minimum confidence of 0.5 for rule-based overrides
        confidence = max(confidence, 0.5)
        # Ensure R:R is at least 1.5 by adjusting TP if needed
        if sl and tp and entry:
            sl_dist = abs(entry - sl)
            tp_dist = abs(tp - entry)
            if sl_dist > 0:
                current_rr = tp_dist / sl_dist
                if current_rr < 1.5:
                    # Extend TP to achieve 1.5 R:R
                    if decision == "BUY":
                        tp = entry + sl_dist * 1.5
                    else:
                        tp = entry - sl_dist * 1.5

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
        similar = await vs.search_similar(analysis.get("technical", {}), limit=20)
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


# ---------------------------------------------------------------------------
# Pre-compute tasks — feed the Redis cache consumed by AnalysisAggregator
# ---------------------------------------------------------------------------

@celery_app.task
def refresh_technical_snapshots():
    """Pre-compute multi-timeframe TA indicator snapshots for all active pairs.

    Runs every 15 minutes (beat_schedule: refresh-technical-snapshots).
    Results are stored in Redis under ``tech_snapshot:{symbol}:{strategy_mode}``
    with a 30-minute TTL, so ``run_full_analysis`` reads a fresh snapshot
    instead of fetching live candles on-demand every 4 hours.

    Gracefully skips any pair that fails (data provider down, etc.) without
    aborting the whole batch.
    """
    async def _run():
        async with get_celery_session()() as db:
            from app import models
            from app.analysis.aggregator import AnalysisAggregator, _TECH_SNAPSHOT_TTL, _numpy_safe_default
            import json, redis.asyncio as aioredis

            active_result = await db.execute(
                select(models.ActivePair).order_by(models.ActivePair.priority)
            )
            active_pairs = active_result.scalars().all()
            if not active_pairs:
                logger.info("refresh_technical_snapshots: no active pairs, skipping")
                return {"refreshed": 0}

            aggregator = AnalysisAggregator()
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            strategy_modes = ("scalping", "day_trading", "swing")
            refreshed = 0

            for pair in active_pairs:
                symbol = pair.symbol
                for mode in strategy_modes:
                    try:
                        # Fetch candles and run pure-Python TA (no LLM call)
                        if mode == "scalping":
                            candles_1m = await aggregator.client.get_historical_candles(symbol, "1m", 300)
                            candles_5m = await aggregator.client.get_historical_candles(symbol, "5m", 300)
                            candles_15m = await aggregator.client.get_historical_candles(symbol, "15m", 200)
                            tf_map = {
                                "1m": aggregator.technical.analyze(candles_1m),
                                "5m": aggregator.technical.analyze(candles_5m),
                                "15m": aggregator.technical.analyze(candles_15m),
                            }
                            tf_list = list(tf_map.values())
                        elif mode == "day_trading":
                            candles_5m = await aggregator.client.get_historical_candles(symbol, "5m", 300)
                            candles_15m = await aggregator.client.get_historical_candles(symbol, "15m", 200)
                            candles_1h = await aggregator.client.get_historical_candles(symbol, "1h", 150)
                            tf_map = {
                                "5m": aggregator.technical.analyze(candles_5m),
                                "15m": aggregator.technical.analyze(candles_15m),
                                "1h": aggregator.technical.analyze(candles_1h),
                            }
                            tf_list = list(tf_map.values())
                        else:  # swing
                            candles_1h = await aggregator.client.get_historical_candles(symbol, "1h", 300)
                            candles_4h = await aggregator.client.get_historical_candles(symbol, "4h", 150)
                            candles_d1 = await aggregator.client.get_historical_candles(symbol, "1d", 100)
                            tf_map = {
                                "1h": aggregator.technical.analyze(candles_1h),
                                "4h": aggregator.technical.analyze(candles_4h),
                                "1d": aggregator.technical.analyze(candles_d1),
                            }
                            tf_list = list(tf_map.values())

                        snapshot = {
                            "timeframes": tf_map,
                            "overall_signal": aggregator._weight_timeframes(*tf_list),
                        }
                        key = f"tech_snapshot:{symbol}:{mode}"
                        await r.setex(key, _TECH_SNAPSHOT_TTL, json.dumps(snapshot, default=_numpy_safe_default))
                        refreshed += 1
                        logger.debug("Tech snapshot refreshed: %s/%s", symbol, mode)
                    except Exception:
                        logger.warning("refresh_technical_snapshots failed for %s/%s", symbol, mode, exc_info=True)

            await r.close()
            logger.info("refresh_technical_snapshots: %d snapshots refreshed (%d pairs × 3 modes)", refreshed, len(active_pairs))
            return {"refreshed": refreshed, "pairs": len(active_pairs)}

    return asyncio.run(_run())


@celery_app.task
def refresh_sentiment_cache():
    """Pre-compute sentiment scores for all active pairs.

    Runs every hour (beat_schedule: refresh-sentiment-cache).
    Stores results in Redis under ``sentiment_cache:{symbol}`` with a 2-hour TTL.
    This keeps sentiment current without adding latency to the LLM analysis cycle.

    COT data is read from the database; retail and news data are fetched live.
    """
    async def _run():
        async with get_celery_session()() as db:
            from app import models
            from app.analysis.sentiment import SentimentAnalyzer
            import json, redis.asyncio as aioredis
            from app.analysis.aggregator import _SENTIMENT_CACHE_TTL, _numpy_safe_default

            active_result = await db.execute(
                select(models.ActivePair).order_by(models.ActivePair.priority)
            )
            active_pairs = active_result.scalars().all()
            if not active_pairs:
                logger.info("refresh_sentiment_cache: no active pairs, skipping")
                return {"refreshed": 0}

            analyzer = SentimentAnalyzer()
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            refreshed = 0

            for pair in active_pairs:
                symbol = pair.symbol
                try:
                    sentiment = await analyzer.analyze(symbol, db=db)
                    key = f"sentiment_cache:{symbol}"
                    await r.setex(key, _SENTIMENT_CACHE_TTL, json.dumps(sentiment, default=_numpy_safe_default))
                    refreshed += 1
                    logger.debug("Sentiment cache refreshed: %s (bias=%s, score=%s)", symbol, sentiment.get("overall_sentiment"), sentiment.get("sentiment_score"))
                except Exception:
                    logger.warning("refresh_sentiment_cache failed for %s", symbol, exc_info=True)

            await r.close()
            logger.info("refresh_sentiment_cache: %d pairs refreshed", refreshed)
            return {"refreshed": refreshed}

    return asyncio.run(_run())


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

            # Initialize Qdrant vector store — hard dependency; fail fast if unhealthy
            from app.services.vector_store import AsyncVectorStore
            vs = AsyncVectorStore()
            try:
                await vs._ensure_collection()
                logger.info("Qdrant is healthy and collection '%s' is ready", vs.client)
            except Exception as exc:
                logger.error("Qdrant hard-dependency failed: %s", exc, exc_info=True)
                return {"status": "error", "reason": f"Qdrant unavailable: {exc}"}

            # News-based trading halt per pair
            news_halt_enabled = await get_setting_bool(db, "news_halt_enabled")
            news_buffer_before = await get_setting_int(db, "news_halt_buffer_before_min") or 15
            news_buffer_after = await get_setting_int(db, "news_halt_buffer_after_min") or 30

            # Gather all analyses first
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            analyses: List[Dict[str, Any]] = []
            for idx, pair in enumerate(active_pairs):
                symbol = pair.symbol
                # Stagger symbol analyses to avoid OpenRouter rate-limit spikes
                if idx > 0:
                    await asyncio.sleep(5)

                try:
                    analysis = await aggregator.gather_all(symbol, strategy_mode=strategy_mode, db=db)
                except Exception as exc:
                    logger.warning("Analysis failed for %s: %s", symbol, exc, exc_info=True)
                    logger.info("HOLD reason for %s: data unavailable — %s", symbol, exc)
                    continue

                # Price gate: skip if market hasn't moved meaningfully since last analysis
                current_price = None
                try:
                    tf = list(analysis.get("technical", {}).get("timeframes", {}).values())[0]
                    current_price = tf.get("indicators", {}).get("close")
                except Exception:
                    pass
                if current_price and not await _should_run_analysis(r, symbol, float(current_price)):
                    reason = "Price gate: market flat since last analysis (<0.005% move)"
                    results.append({"symbol": symbol, "decision": "HOLD", "confidence": 0.0, "reason": reason})
                    db_decision = models.AIDecision(
                        symbol=symbol,
                        decision="HOLD",
                        confidence=0.0,
                        rationale=reason,
                        model_used="price_gate",
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
                        "rationale": reason,
                        "manual_override": manual_override,
                        "strategy_mode": strategy_mode,
                    })
                    logger.info("Price gate skipped %s (price %.5f, flat)", symbol, current_price)
                    continue
                if current_price:
                    await _store_last_price(r, symbol, float(current_price))

                analysis["symbol"] = symbol
                analyses.append(analysis)
            try:
                await r.close()
            except Exception:
                pass

            # Pattern-based learning filter: skip pairs/sessions with poor historical win rates
            pattern_priors = None
            try:
                from app.services.pattern_extractor import PatternExtractor
                pe = PatternExtractor()
                pattern_priors = await pe.get_cached_priors()
            except Exception:
                pass

            # Check news halt for each pair
            allowed_analyses = []
            for analysis in analyses:
                symbol = analysis["symbol"]

                # Learning filter: skip if this pair or session has poor historical win rates
                if pattern_priors:
                    from app.services.sessions import classify_session
                    current_session = classify_session(utc_now()) or "unknown"
                    session_stats = pattern_priors.get("by_session", {})
                    symbol_stats = pattern_priors.get("by_symbol", {})
                    pair_dir_stats = pattern_priors.get("by_symbol_direction", {})
                    skip_reason = None

                    # Check session win rate (need 5+ trades to be confident)
                    sess_key = current_session.replace("asian", "asia").replace("london_ny_overlap", "ny")
                    for sk in [sess_key, current_session]:
                        if sk in session_stats:
                            stats = session_stats[sk]
                            if stats.get("count", 0) >= 5 and stats.get("win_rate", 1.0) < 0.25:
                                skip_reason = f"{sk} session win rate {stats['win_rate']:.0%} over {stats['count']} trades"
                                break

                    # Check per-pair win rate (need 8+ trades to be confident)
                    if not skip_reason and symbol in symbol_stats:
                        stats = symbol_stats[symbol]
                        if stats.get("count", 0) >= 8 and stats.get("win_rate", 1.0) < 0.30:
                            skip_reason = f"{symbol} pair win rate {stats['win_rate']:.0%} over {stats['count']} trades"

                    if skip_reason:
                        reason = f"Pattern filter: {skip_reason} — skipping"
                        results.append({"symbol": symbol, "decision": "HOLD", "confidence": 0.0, "reason": reason})
                        logger.info("[PATTERN] %s: %s", symbol, reason)
                        continue

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
                    team_meta_enabled = await get_setting_bool(db, "team_meta_enabled")
                    for analysis in allowed_analyses:
                        symbol = analysis["symbol"]
                        v2_result = await team.decide(symbol, strategy_mode, analysis)

                        # ------------------------------------------------------------------
                        # TeamMetaModel soft confidence adjuster (Route B)
                        # ------------------------------------------------------------------
                        if team_meta_enabled and v2_result["decision"] in ("BUY", "SELL"):
                            try:
                                from app.services.ml.team_meta_model import TeamMetaModel
                                tmm = TeamMetaModel()
                                meta_score = tmm.predict(
                                    v2_result.get("analyst_opinions"),
                                    v2_result.get("verifier_verdict"),
                                    v2_result.get("lead_model"),
                                )
                                if meta_score is not None:
                                    old_conf = float(v2_result["confidence"])
                                    adjusted = old_conf * (0.70 + 0.60 * meta_score)
                                    adjusted = min(adjusted, 1.0)
                                    v2_result["confidence"] = adjusted
                                    v2_result["rationale"] += (
                                        f" | TeamMeta: score={meta_score:.2f}, "
                                        f"conf {old_conf:.2f} -> {adjusted:.2f}"
                                    )
                                    logger.info(
                                        "TeamMeta adjusted %s confidence: %.2f -> %.2f (score=%.2f)",
                                        symbol, old_conf, adjusted, meta_score,
                                    )
                            except Exception as tmm_exc:
                                logger.warning("TeamMetaModel adjustment failed for %s: %s", symbol, tmm_exc)

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
                    verifier_confidence=v2_results.get(symbol, {}).get("verifier_confidence"),
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
                _decision_id = db_decision.id  # capture before any sync calls
                _decision_qdrant_id = getattr(db_decision, "qdrant_point_id", None)
                # Log TradeDecisionEvent for audit/learning (v2 path)
                try:
                    from datetime import datetime, timezone
                    event = models.TradeDecisionEvent(
                        trade_id=None,
                        ts=db_decision.timestamp or datetime.now(timezone.utc),
                        kind="ENTRY",
                        source="AI",
                        action=db_decision.decision,
                        snapshot=_clean_numpy({
                            "symbol": symbol,
                            "session": analysis.get("session"),
                            "regime": regime_info.get("regime"),
                            "lead_model": v2_results.get(symbol, {}).get("lead_model"),
                            "verdict": v2_results.get(symbol, {}).get("verifier_verdict"),
                            "analyst_opinions": v2_results.get(symbol, {}).get("analyst_opinions"),
                        }),
                        rationale=db_decision.rationale,
                        confidence=db_decision.confidence,
                        model_used=db_decision.lead_model or db_decision.model_used,
                    )
                    db.add(event)
                    await db.commit()
                    await db.refresh(event)
                except Exception as ev:
                    logger.warning("Failed to log TradeDecisionEvent for %s: %s", symbol, ev)


                # Persist regime label to market_regimes table
                try:
                    mr = models.MarketRegime(
                        timestamp=utc_now(),
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
                point_id = int(_decision_id)
                try:
                    await vs.upsert_snapshot(
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
                    logger.warning("Failed to upsert Qdrant snapshot for decision %s", _decision_id, exc_info=True)

                # Persist snapshot metadata in SQL for audit + reporting
                try:
                    mss = models.MarketStateSnapshot(
                        symbol=symbol,
                        strategy_mode=strategy_mode,
                        decision=decision.decision,
                        confidence=decision.confidence,
                        qdrant_point_id=str(point_id),
                    )
                    db.add(mss)
                    await db.commit()
                except Exception:
                    logger.warning("Failed to insert MarketStateSnapshot for decision %s", _decision_id, exc_info=True)
                    await db.rollback()

                # Back-link the Qdrant point ID to the AIDecision record
                try:
                    # Re-fetch decision to avoid stale object issues
                    d_res = await db.execute(select(models.AIDecision).where(models.AIDecision.id == _decision_id))
                    db_decision_refresh = d_res.scalar_one_or_none()
                    if db_decision_refresh:
                        db_decision_refresh.qdrant_point_id = point_id
                        await db.commit()
                except Exception:
                    logger.warning("Failed to set qdrant_point_id on AIDecision %s", _decision_id, exc_info=True)
                    await db.rollback()

                # Broadcast AI decision to all connected clients
                await broadcast_ai_decision({
                    "id": _decision_id,
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

                        # Clamp SL/TP to ATR-based limits instead of blocking
                        if atr and atr > 0 and decision.entry_price:
                            strategy_mode_val = await risk._get_strategy_mode(db)
                            limits = {
                                "scalping": {"sl_min": 0.3, "sl_max": 2.0, "tp_min": 0.5, "tp_max": 3.0},
                                "day_trading": {"sl_min": 0.3, "sl_max": 3.0, "tp_min": 0.8, "tp_max": 5.0},
                                "swing": {"sl_min": 0.5, "sl_max": 5.0, "tp_min": 1.0, "tp_max": 8.0},
                            }
                            lim = limits.get(strategy_mode_val, limits["scalping"])
                            entry = decision.entry_price
                            sl = decision.stop_loss
                            tp = decision.take_profit
                            sl_dist = abs(entry - sl) if sl else 0
                            tp_dist = abs(tp - entry) if tp else 0
                            sl_atr = sl_dist / atr if sl_dist > 0 else 0
                            tp_atr = tp_dist / atr if tp_dist > 0 else 0

                            # Clamp SL to [sl_min, sl_max] ATR (use 95% of max to avoid float boundary)
                            if sl_atr > lim["sl_max"]:
                                new_sl_dist = atr * lim["sl_max"] * 0.95
                                if decision.decision == "BUY":
                                    decision.stop_loss = round(entry - new_sl_dist, 5)
                                else:
                                    decision.stop_loss = round(entry + new_sl_dist, 5)
                                logger.info("[CLAMP] %s: SL adjusted from %.2fx to %.2fx ATR", symbol, sl_atr, lim["sl_max"] * 0.95)
                            elif sl_atr < lim["sl_min"] and sl_atr > 0:
                                new_sl_dist = atr * lim["sl_min"] * 1.05
                                if decision.decision == "BUY":
                                    decision.stop_loss = round(entry - new_sl_dist, 5)
                                else:
                                    decision.stop_loss = round(entry + new_sl_dist, 5)
                                logger.info("[CLAMP] %s: SL adjusted from %.2fx to %.2fx ATR", symbol, sl_atr, lim["sl_min"] * 1.05)

                            # Clamp TP to [tp_min, tp_max] ATR (use 95% of max to avoid float boundary)
                            if tp_atr > lim["tp_max"]:
                                new_tp_dist = atr * lim["tp_max"] * 0.95
                                if decision.decision == "BUY":
                                    decision.take_profit = round(entry + new_tp_dist, 5)
                                else:
                                    decision.take_profit = round(entry - new_tp_dist, 5)
                                logger.info("[CLAMP] %s: TP adjusted from %.2fx to %.2fx ATR", symbol, tp_atr, lim["tp_max"] * 0.95)
                            elif tp_atr < lim["tp_min"] and tp_atr > 0:
                                new_tp_dist = atr * lim["tp_min"] * 1.05
                                if decision.decision == "BUY":
                                    decision.take_profit = round(entry + new_tp_dist, 5)
                                else:
                                    decision.take_profit = round(entry - new_tp_dist, 5)
                                logger.info("[CLAMP] %s: TP adjusted from %.2fx to %.2fx ATR", symbol, tp_atr, lim["tp_min"] * 1.05)

                            # Recalculate R:R
                            new_sl_dist = abs(entry - decision.stop_loss)
                            new_tp_dist = abs(decision.take_profit - entry)
                            if new_sl_dist > 0:
                                decision.risk_reward = round(new_tp_dist / new_sl_dist, 2)

                        # 1. ATR-based SL/TP validation (after clamping, should pass)
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
                            # get_setting_float already imported at module level
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
                                "id": _decision_id,
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
                            "id": _decision_id,
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
    """Hourly task: compute pattern priors from closed trades and cache in Redis."""
    async def _compute():
        async with get_celery_session()() as db:
            from app import models
            from app.services.pattern_extractor import PatternExtractor
            from app.services.sessions import classify_session

            result = await db.execute(
                select(models.Trade).where(models.Trade.status == models.TradeStatus.CLOSED)
                .order_by(models.Trade.close_time.desc())
                .limit(500)
            )
            trades = result.scalars().all()

            trade_dicts = []
            for t in trades:
                # Use stored session_at_open if available, otherwise classify from open_time
                session = t.session_at_open or "unknown"
                if session == "unknown" and t.open_time:
                    session = classify_session(t.open_time) or "unknown"
                # Normalize session names
                session = session.replace("asian", "asia").replace("london_ny_overlap", "ny")
                trade_dicts.append({
                    "symbol": t.symbol,
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                    "pnl": t.pnl or 0,
                    "regime": session,
                    "session": session,
                    "pattern_tags": [t.strategy_mode or "scalping"],
                })

            extractor = PatternExtractor()
            priors = extractor.compute_pattern_priors(trade_dicts)
            await extractor.cache_priors(priors)
            logger.info("compute_pattern_priors: cached priors for %d trades", len(trades))

    asyncio.run(_compute())


@celery_app.task
def update_model_performance():
    """Hourly task: populate ModelPerformance table from recent decisions."""
    async def _update():
        async with get_celery_session()() as db:
            from sqlalchemy import func
            from datetime import datetime, timedelta, timezone
            from app import models

            since = datetime.now(timezone.utc) - timedelta(hours=24)
            result = await db.execute(
                select(models.Trade)
                .where(models.Trade.status == models.TradeStatus.CLOSED)
                .where(models.Trade.close_time >= since)
                .where(models.Trade.ai_decision_id.isnot(None))
            )
            trades = result.scalars().all()

            # Group by model_used via joined AIDecision
            by_model = {}
            for t in trades:
                d_result = await db.execute(
                    select(models.AIDecision)
                    .where(models.AIDecision.id == t.ai_decision_id)
                )
                decision = d_result.scalar_one_or_none()
                model = decision.model_used if decision else "unknown"
                by_model.setdefault(model, []).append(t)

            for model, model_trades in by_model.items():
                wins = sum(1 for t in model_trades if (t.pnl or 0) > 0)
                losses = sum(1 for t in model_trades if (t.pnl or 0) <= 0)
                total = wins + losses
                if total == 0:
                    continue
                win_rate = wins / total
                avg_pnl = sum(t.pnl or 0 for t in model_trades) / total
                # Get avg confidence from associated decisions
                confidences = []
                for t in model_trades:
                    if t.ai_decision_id:
                        d_res = await db.execute(
                            select(models.AIDecision.confidence)
                            .where(models.AIDecision.id == t.ai_decision_id)
                        )
                        c = d_res.scalar()
                        if c is not None:
                            confidences.append(c)
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

                # Check if entry exists and update, else insert
                existing = await db.execute(
                    select(models.ModelPerformance)
                    .where(models.ModelPerformance.model == model)
                    .where(models.ModelPerformance.domain == "overall")
                    .where(models.ModelPerformance.window == "24h")
                )
                mp = existing.scalar_one_or_none()
                if mp:
                    mp.trades = total
                    mp.winning_trades = wins
                    mp.losing_trades = losses
                    mp.win_rate = win_rate
                    mp.avg_pnl = avg_pnl
                    mp.avg_confidence = avg_confidence
                    mp.updated_at = datetime.now(timezone.utc)
                else:
                    mp = models.ModelPerformance(
                        model=model,
                        domain="overall",
                        window="24h",
                        trades=total,
                        winning_trades=wins,
                        losing_trades=losses,
                        win_rate=win_rate,
                        expectancy=avg_pnl,
                        avg_pnl=avg_pnl,
                        avg_confidence=avg_confidence,
                        updated_at=datetime.now(timezone.utc),
                    )
                    db.add(mp)
            await db.commit()
            logger.info("update_model_performance: updated %d models", len(by_model))

            # Cache win rates + AUC/Brier calibration in Redis
            try:
                import redis.asyncio as aioredis
                from app.config import get_settings
                r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
                for model, model_trades in by_model.items():
                    wins = sum(1 for t in model_trades if (t.pnl or 0) > 0)
                    losses = sum(1 for t in model_trades if (t.pnl or 0) <= 0)
                    total = wins + losses
                    win_rate = wins / total if total else 0.0
                    avg_pnl = sum(t.pnl or 0 for t in model_trades) / total if total else 0.0
                    await r.hset("ai:model:performance", model, json.dumps({"win_rate": win_rate, "avg_pnl": avg_pnl, "trades": total}))

                    # AUC and Brier calibration
                    try:
                        from sklearn.metrics import roc_auc_score, brier_score_loss
                        confidences = []
                        y_true = []
                        for t in model_trades:
                            d = None
                            if t.ai_decision_id:
                                d_res = await db.execute(
                                    select(models.AIDecision.confidence)
                                    .where(models.AIDecision.id == t.ai_decision_id)
                                )
                                d = d_res.scalar()
                            confidences.append(float(d) if d is not None else 0.5)
                            y_true.append(1 if (t.pnl or 0) > 0 else 0)
                        if len(set(y_true)) > 1 and confidences:
                            auc = float(roc_auc_score(y_true, confidences))
                            brier = float(brier_score_loss(y_true, confidences))
                        else:
                            auc = None
                            brier = None
                        await r.hset("ai:model:calibration", model, json.dumps({
                            "auc": auc,
                            "brier": brier,
                            "samples": total,
                            "wins": wins,
                            "losses": losses,
                        }))
                    except Exception:
                        logger.warning("AUC/Brier cache failed for %s", model, exc_info=True)
                await r.expire("ai:model:performance", 86400)
                await r.expire("ai:model:calibration", 86400)
                await r.aclose()
            except Exception:
                logger.warning("Failed to cache model performance in Redis", exc_info=True)

    asyncio.run(_update())


@celery_app.task
def train_entry_model():
    """On-demand / scheduled task: retrain XGBoost entry quality model."""
    async def _train():
        async with get_celery_session()() as db:
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
                    "macro": decision.daily_bias or {},
                }
                features = FeatureStore.compute_entry_features(analysis)
                label = 1 if (t.pnl or 0) > 0 else 0
                decisions_data.append({
                    "features": features,
                    "label": label,
                    "symbol": t.symbol,
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
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
def retrain_all_models():
    """Scheduled task: retrain both EntryQualityModel and TeamMetaModel.

    Trains on all closed trades with AI decisions from the last 90 days.
    Winners are weighted 2x more than losers to bias learning toward
    winning patterns.
    """
    async def _train():
        async with get_celery_session()() as db:
            from datetime import datetime, timedelta, timezone
            from app import models
            from app.services.feature_store import FeatureStore
            from app.services.ml.entry_model import EntryQualityModel
            from app.services.ml.team_meta_model import (
                TeamMetaModel,
                _extract_analyst_features,
                _extract_verifier_features,
            )
            from app.services.ml.multitimeframe_features import compute_multitimeframe_features
            import pandas as pd

            since = datetime.now(timezone.utc) - timedelta(days=90)
            result = await db.execute(
                select(models.Trade)
                .where(models.Trade.status == models.TradeStatus.CLOSED)
                .where(models.Trade.close_time >= since)
                .where(models.Trade.ai_decision_id.isnot(None))
                .order_by(models.Trade.close_time)
                .limit(3000)
            )
            trades = result.scalars().all()
            logger.info("retrain_all_models: %d closed trades found", len(trades))

            if len(trades) < 50:
                logger.warning("retrain_all_models: insufficient data (%d samples), skipping", len(trades))
                return

            entry_data = []
            team_data = []
            for t in trades:
                d_result = await db.execute(
                    select(models.AIDecision).where(models.AIDecision.id == t.ai_decision_id)
                )
                decision = d_result.scalar_one_or_none()
                if not decision:
                    continue
                label = 1 if (t.pnl or 0) > 0 else 0
                try:
                    mt = await compute_multitimeframe_features(db, t.symbol, decision.created_at or t.created_at)
                except Exception:
                    mt = {}
                analysis = {
                    "technical": decision.technical_snapshot or {},
                    "fundamental": decision.fundamental_snapshot or {},
                    "sentiment": decision.sentiment_snapshot or {},
                    "macro": decision.daily_bias or {},
                }
                base = FeatureStore.compute_entry_features(analysis)
                entry_data.append({
                    "features": {**base, **mt},
                    "label": label,
                    "symbol": t.symbol,
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
                })
                tf = {}
                tf.update(_extract_analyst_features(decision.analyst_opinions))
                tf.update(_extract_verifier_features(decision.verifier_verdict, decision.lead_model))
                tf["label"] = label
                team_data.append(tf)

            # Train EntryQualityModel (win_weight=2.0 biases toward winning patterns)
            if len(entry_data) >= 50:
                df_entry = FeatureStore.export_training_set(entry_data)
                entry_model = EntryQualityModel()
                entry_metrics = entry_model.train(df_entry, win_weight=2.0)
                logger.info(
                    "retrain_all_models: EntryQualityModel trained — train_auc=%.3f test_auc=%.3f n=%d",
                    entry_metrics.get("train_auc", 0),
                    entry_metrics.get("test_auc", 0),
                    len(entry_data),
                )

            # Train TeamMetaModel (win_weight=2.0)
            if len(team_data) >= 50:
                df_team = pd.DataFrame(team_data)
                team_model = TeamMetaModel()
                team_metrics = team_model.train(df_team, win_weight=2.0)
                logger.info(
                    "retrain_all_models: TeamMetaModel trained — train_auc=%.3f test_auc=%.3f n=%d",
                    team_metrics.get("train_auc", 0),
                    team_metrics.get("test_auc", 0),
                    len(team_data),
                )

    asyncio.run(_train())


@celery_app.task
def rolling_backtest_30d():
    """Nightly task: run rolling 30-day backtest on recent closed trades."""
    async def _run():
        async with get_celery_session()() as db:
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
                    "direction": t.direction.value if hasattr(t.direction, "value") else str(t.direction),
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
            regime_trades = [{"regime": t.session_at_open or "unknown", "pnl": t.pnl or 0} for t in trades]
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
                model="paper_trading_kpi",
                domain="overall",
                window="7d",
                trades=report.get("total_trades", 0),
                winning_trades=report.get("wins", 0),
                losing_trades=report.get("losses", 0),
                win_rate=report.get("win_rate", 0),
                expectancy=report.get("net_pnl", 0),
                avg_pnl=report.get("net_pnl", 0),
                avg_confidence=report.get("avg_exit_quality", 0),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)
            await db.commit()
            logger.info("daily_kpi_snapshot: win_rate=%.2f trades=%d",
                        report.get("win_rate", 0), report.get("total_trades", 0))

    asyncio.run(_snapshot())

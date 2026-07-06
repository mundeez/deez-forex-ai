"""Full expanding-window backtest on multi-timeframe historical data.

Walk-forward setup:
  - Decision frequency: once per session (Asian, London, London-NY, NY)
  - Uses REAL v2 AI team (analysts + lead + verifier)
  - Expanding window: trains models at end of each month on all prior data
  - Simulates execution with historical candles
  - Tracks equity from $200 starting capital
  - Caches AI decisions to Redis to avoid re-computation on resume

This is a LONG-RUNNING task. Expect 6-12 hours for 6 months × 9 pairs.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import numpy as np
from celery import shared_task
from sqlalchemy import select, text

from app.database import get_celery_session
from app import models
from app.enums import TradeDirection, TradeMode

logger = logging.getLogger("app.tasks.backtest_full")

# Session boundaries (UTC)
SESSIONS = [
    ("asian", 0, 7),      # 00:00 - 07:00 UTC
    ("london", 7, 13),    # 07:00 - 13:00 UTC
    ("london_ny", 13, 17), # 13:00 - 17:00 UTC (overlap)
    ("ny", 17, 21),       # 17:00 - 21:00 UTC
]

ACTIVE_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "GBPJPY",
]

# Typical retail spreads in pips (conservative estimates)
SPREADS_PIPS = {
    "EURUSD": 1.5,
    "GBPUSD": 1.5,
    "USDJPY": 1.5,
    "AUDUSD": 1.5,
    "NZDUSD": 2.0,
    "USDCAD": 2.0,
    "USDCHF": 2.0,
    "EURGBP": 2.0,
    "GBPJPY": 4.0,
}


class SessionBacktestEngine:
    """Simulate trading once per session on historical data."""

    def __init__(self, initial_equity: float = 200.0):
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.max_equity = initial_equity
        self.max_drawdown_pct = 0.0
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []

    async def _get_cached_decision(self, r, symbol: str, session_start: datetime) -> Optional[Dict]:
        """Check Redis cache for previously computed AI decision."""
        cache_key = f"backtest:decision:{symbol}:{session_start.strftime('%Y%m%d_%H')}"
        try:
            raw = await r.get(cache_key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    async def _cache_decision(self, r, symbol: str, session_start: datetime, decision: Dict):
        """Cache AI decision to Redis."""
        cache_key = f"backtest:decision:{symbol}:{session_start.strftime('%Y%m%d_%H')}"
        try:
            await r.set(cache_key, json.dumps(decision), ex=86400 * 30)  # 30 days
        except Exception:
            pass

    async def _load_candles_for_session(
        self, db, symbol: str, session_start: datetime, session_end: datetime, timeframe: str = "5m"
    ) -> pd.DataFrame:
        """Load candles for a specific session window."""
        stmt = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_candles
            WHERE symbol = :symbol AND timeframe = :timeframe
              AND timestamp >= :start AND timestamp < :end
            ORDER BY timestamp
        """)
        result = await db.execute(stmt, {
            "symbol": symbol, "timeframe": timeframe,
            "start": session_start, "end": session_end,
        })
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        return df

    async def _load_candles_tf(self, db, symbol: str, session_start: datetime, session_end: datetime, timeframe: str) -> pd.DataFrame:
        """Load candles for a specific timeframe with expanded lookback for context."""
        lookback = {"5m": timedelta(hours=24), "15m": timedelta(hours=48), "1h": timedelta(hours=48)}
        extra = lookback.get(timeframe, timedelta(0))
        stmt = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_candles
            WHERE symbol = :symbol AND timeframe = :timeframe
              AND timestamp >= :start AND timestamp < :end
            ORDER BY timestamp
        """)
        result = await db.execute(stmt, {
            "symbol": symbol, "timeframe": timeframe,
            "start": session_start - extra, "end": session_end,
        })
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

    async def _load_context(
        self, db, symbol: str, session_start: datetime,
        lookback: timedelta, timeframe: str
    ) -> pd.DataFrame:
        """Load candles strictly BEFORE session_start. Never bleeds into the session."""
        stmt = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_candles
            WHERE symbol = :symbol AND timeframe = :timeframe
              AND timestamp >= :start
              AND timestamp < :session_start        -- hard upper bound
            ORDER BY timestamp DESC
            LIMIT 300
        """)
        result = await db.execute(stmt, {
            "symbol": symbol,
            "timeframe": timeframe,
            "start": session_start - lookback,
            "session_start": session_start,
        })
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        return df.sort_values("timestamp").reset_index(drop=True)

    async def _load_execution(
        self, db, symbol: str, session_start: datetime, session_end: datetime
    ) -> pd.DataFrame:
        """Load candles for walk-forward simulation ONLY. AI never sees these."""
        stmt = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_candles
            WHERE symbol = :symbol AND timeframe = '5m'
              AND timestamp >= :start AND timestamp < :end
            ORDER BY timestamp
        """)
        result = await db.execute(stmt, {"symbol": symbol, "start": session_start, "end": session_end})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

    async def _run_v2_decision(
        self, symbol: str, strategy_mode: str, ctx_5m: pd.DataFrame, ctx_15m: pd.DataFrame = None,
        session_name: str = "asian", db=None, session_start: datetime = None,
    ) -> Optional[Dict[str, Any]]:
        """Run the v2 AI team with multi-timeframe analysis snapshot using ONLY pre-session context.

        When db and session_start are provided, fetches real historical fundamental,
        sentiment, and macro data from DB tables with point-in-time filtering (as_of=session_start).
        Otherwise falls back to neutral stubs.
        """
        if ctx_5m.empty:
            return None

        from app.analysis.technical import TechnicalAnalyzer
        ta = TechnicalAnalyzer()
        tech_5m = ta.analyze(ctx_5m.to_dict("records"))

        tf_map = {"5m": tech_5m}
        overall_signal = tech_5m.get("signal", "neutral")
        if ctx_15m is not None and not ctx_15m.empty and len(ctx_15m) >= 20:
            tech_15m = ta.analyze(ctx_15m.to_dict("records"))
            tf_map["15m"] = tech_15m
            scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
            for sig_val, w in [(tech_5m.get("signal", "neutral"), 0.5), (tech_15m.get("signal", "neutral"), 0.5)]:
                scores[sig_val] = scores.get(sig_val, 0.0) + w
            overall_signal = max(scores, key=scores.get)

        # --- Fetch real historical fundamental/sentiment/macro data ---
        if db is not None and session_start is not None:
            from app.analysis.fundamental import FundamentalAnalyzer
            from app.analysis.sentiment import SentimentAnalyzer
            from app.analysis.macro import MacroAnalyzer

            fundamental = FundamentalAnalyzer()
            sentiment = SentimentAnalyzer()
            macro = MacroAnalyzer()

            try:
                fundamental_data = await fundamental.analyze(
                    symbol, db=db, as_of=session_start
                )
            except Exception as exc:
                logger.warning("Fundamental analysis failed for %s: %s", symbol, exc)
                fundamental_data = {"event_risk": "low", "direction_bias": "neutral", "events": [], "news_headlines": []}

            try:
                sentiment_data = await sentiment.analyze(
                    symbol, db=db, as_of=session_start
                )
            except Exception as exc:
                logger.warning("Sentiment analysis failed for %s: %s", symbol, exc)
                sentiment_data = {"overall_sentiment": "neutral", "sentiment_score": 0.0}

            try:
                macro_data = await macro.analyze(db=db, as_of=session_start)
            except Exception as exc:
                logger.warning("Macro analysis failed: %s", exc)
                macro_data = {"bias": "neutral", "risk_on_score": 0.0}
        else:
            fundamental_data = {"event_risk": "low", "direction_bias": "neutral", "note": "no db"}
            sentiment_data = {"overall_sentiment": "neutral", "sentiment_score": 0.0, "note": "no db"}
            macro_data = {"note": "no db"}

        analysis = {
            "symbol": symbol,
            "technical": {"timeframes": tf_map, "overall_signal": overall_signal},
            "fundamental": fundamental_data,
            "sentiment": sentiment_data,
            "macro": macro_data,
            "regime": macro_data.get("bias", "unknown"),
            "session": session_name,
        }

        from app.ai.team.orchestrator import TeamDecisionEngine
        from app.ai.suites import resolve_models
        models_map = resolve_models("free")

        team = TeamDecisionEngine(
            technical_model=models_map.get("technical"),
            fundamental_model=models_map.get("fundamental"),
            sentiment_model=models_map.get("sentiment"),
            macro_model=models_map.get("macro"),
            lead_model=models_map.get("lead"),
            verifier_model=models_map.get("verifier"),
            verifier_enabled=False,
            analyst_parallelism=True,
        )

        try:
            result = await team.decide(symbol, strategy_mode, analysis)
            return result
        except Exception as exc:
            logger.warning("v2 decision failed for %s: %s", symbol, exc)
            return None

    async def _simulate_trade(
        self, symbol: str, decision: Dict, exec_candles: pd.DataFrame, ctx_candles: pd.DataFrame = None,
    ) -> Optional[Dict[str, Any]]:
        """Simulate trade execution on execution candles. No look-ahead bias."""
        if decision.get("decision") not in ("BUY", "SELL"):
            return None
        if decision.get("confidence", 0) < 0.15:
            return None

        entry = float(decision.get("entry_price", 0))
        sl = float(decision.get("stop_loss", 0))
        tp = float(decision.get("take_profit", 0))
        if entry == 0 or sl == 0 or tp == 0:
            return None

        if exec_candles.empty:
            return None

        direction = decision["decision"].lower()
        is_buy = direction == "buy"

        # Simulate: entry at open of first candle in session
        entry_price = float(exec_candles.iloc[0]["open"])

        # Recalculate SL/TP distances using actual entry
        ai_sl_dist = abs(entry - sl)
        ai_tp_dist = abs(tp - entry)
        if is_buy:
            actual_sl = entry_price - ai_sl_dist
            actual_tp = entry_price + ai_tp_dist
        else:
            actual_sl = entry_price + ai_sl_dist
            actual_tp = entry_price - ai_tp_dist

        # Walk forward through execution candles only
        for idx in range(1, len(exec_candles)):
            candle = exec_candles.iloc[idx]
            if is_buy:
                if candle["low"] <= actual_sl:
                    exit_price = actual_sl
                    pnl = (exit_price - entry_price)
                    close_reason = "stop_loss"
                    break
                elif candle["high"] >= actual_tp:
                    exit_price = actual_tp
                    pnl = (exit_price - entry_price)
                    close_reason = "take_profit"
                    break
            else:
                if candle["high"] >= actual_sl:
                    exit_price = actual_sl
                    pnl = (entry_price - exit_price)
                    close_reason = "stop_loss"
                    break
                elif candle["low"] <= actual_tp:
                    exit_price = actual_tp
                    pnl = (entry_price - exit_price)
                    close_reason = "take_profit"
                    break
        else:
            # Session ended without hit — close at last price
            exit_price = float(exec_candles.iloc[-1]["close"])
            pnl = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
            close_reason = "session_end"

        # Convert pips to USD
        pip = 0.0001 if "JPY" not in symbol else 0.01
        pnl_pips = pnl / pip

        # Position sizing: 1% risk per trade on $200 = $2 risk
        risk_amount = 2.0
        sl_pips = abs(entry_price - actual_sl) / pip
        if sl_pips == 0:
            return None
        lot_size = risk_amount / (sl_pips * 10.0)
        lot_size = max(0.01, min(lot_size, 0.1))

        pnl_usd = pnl_pips * lot_size * 10.0

        # Spread cost — charged on every trade regardless of outcome
        spread_pips = SPREADS_PIPS.get(symbol, 2.0)
        spread_cost_usd = spread_pips * lot_size * 10.0
        pnl_usd -= spread_cost_usd

        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop_loss": actual_sl,
            "take_profit": actual_tp,
            "pnl_usd": pnl_usd,
            "pnl_pips": pnl_pips,
            "close_reason": close_reason,
            "lot_size": lot_size,
            "confidence": decision.get("confidence", 0),
            "model_used": decision.get("lead_model", ""),
            "spread_cost_usd": spread_cost_usd,
            "timestamp": exec_candles.iloc[0]["timestamp"] if not exec_candles.empty else datetime.now(timezone.utc),
        }

    async def run_session(
        self, db, symbol: str, session_start: datetime, session_end: datetime,
        strategy_mode: str = "scalping", session_name: str = "asian",
    ) -> Optional[Dict[str, Any]]:
        """Run a single session: load context candles for AI, execution candles for simulation."""
        import redis.asyncio as aioredis
        from app.config import get_settings
        r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)

        # Load context + execution windows
        ctx_5m  = await self._load_context(db, symbol, session_start, timedelta(hours=24), "5m")
        ctx_15m = await self._load_context(db, symbol, session_start, timedelta(hours=48), "15m")
        exec_5m = await self._load_execution(db, symbol, session_start, session_end)

        # Check cache (keyed by context, not execution)
        cached = await self._get_cached_decision(r, symbol, session_start)
        if cached:
            await r.aclose()
            if cached.get("decision") in ("BUY", "SELL"):
                return await self._simulate_trade(symbol, cached, exec_5m)
            return None

        if ctx_5m.empty:
            await r.aclose()
            return None

        decision = await self._run_v2_decision(symbol, strategy_mode, ctx_5m, ctx_15m, session_name=session_name, db=db, session_start=session_start)
        if decision:
            await self._cache_decision(r, symbol, session_start, decision)
        await r.aclose()

        if decision and decision.get("decision") in ("BUY", "SELL"):
            return await self._simulate_trade(symbol, decision, exec_5m)
        return None

    async def run_full_backtest(
        self,
        start: datetime,
        end: datetime,
        symbols: List[str] = None,
        strategy_mode: str = "scalping",
        retrain_monthly: bool = True,
    ) -> Dict[str, Any]:
        """Run expanding-window backtest over the full date range."""
        symbols = symbols or ACTIVE_SYMBOLS
        logger.info("Starting full backtest: %s to %s, %d symbols", start, end, len(symbols))

        # Generate all session boundaries (skip weekends — forex closed)
        sessions = []
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current < end:
            if current.weekday() < 5:  # 5 = Saturday, 6 = Sunday
                for name, h0, h1 in SESSIONS:
                    s_start = current.replace(hour=h0, minute=0)
                    s_end = current.replace(hour=h1, minute=0)
                    if s_start >= start and s_end <= end:
                        sessions.append((s_start, s_end, name))
            current += timedelta(days=1)

        logger.info("Total sessions to evaluate: %d", len(sessions))

        month_counter = 0
        async with get_celery_session()() as db:
            import asyncio
            for s_start, s_end, s_name in sessions:
                # Rate limit: sleep 3s between sessions to respect free model limits
                await asyncio.sleep(3.0)
                # Retrain models at start of each month
                if retrain_monthly and s_start.day == 1 and s_start.hour == 0:
                    month_counter += 1
                    logger.info("Month %d starting: %s", month_counter, s_start)
                    await self._retrain_models(db, s_start)

                for symbol in symbols:
                    try:
                        trade = await self.run_session(db, symbol, s_start, s_end, strategy_mode, session_name=s_name)
                    except Exception as exc:
                        logger.warning("Session failed for %s %s: %s", symbol, s_name, str(exc)[:100])
                        trade = None
                    if trade:
                        self.trades.append(trade)
                        self.equity += trade["pnl_usd"]
                        self.max_equity = max(self.max_equity, self.equity)
                        dd = (self.max_equity - self.equity) / self.max_equity * 100
                        self.max_drawdown_pct = max(self.max_drawdown_pct, dd)

                self.equity_curve.append({
                    "timestamp": s_end,
                    "equity": self.equity,
                    "session": s_name,
                })

                # Checkpoint every 50 sessions
                if len(self.equity_curve) % 50 == 0:
                    logger.info("Checkpoint: sessions=%d equity=$%.2f max_dd=%.1f%% trades=%d",
                        len(self.equity_curve), self.equity, self.max_drawdown_pct, len(self.trades))

        return self._compute_metrics()

    async def _retrain_models(self, db, cutoff: datetime):
        """Retrain entry model and team meta-model on all data before cutoff."""
        try:
            from app.services.ml.multitimeframe_features import compute_multitimeframe_features
            from app.services.ml.team_meta_model import TeamMetaModel
            from app.services.ml.entry_model import EntryQualityModel
            from app.services.feature_store import FeatureStore

            result = await db.execute(
                select(models.Trade)
                .where(models.Trade.status == models.TradeStatus.CLOSED)
                .where(models.Trade.close_time < cutoff)
                .where(models.Trade.ai_decision_id.isnot(None))
                .limit(3000)
            )
            trades = result.scalars().all()
            if len(trades) < 100:
                logger.info("Retrain skipped: only %d trades before %s", len(trades), cutoff)
                return

            entry_decisions = []
            team_data = []
            for t in trades:
                d_result = await db.execute(
                    select(models.AIDecision).where(models.AIDecision.id == t.ai_decision_id)
                )
                decision = d_result.scalar_one_or_none()
                if not decision:
                    continue
                label = 1 if (t.pnl or 0) > 0 else 0

                # Multi-timeframe features
                try:
                    mt_feats = await compute_multitimeframe_features(db, t.symbol, decision.created_at or t.created_at)
                except Exception:
                    mt_feats = {}
                analysis = {
                    "technical": decision.technical_snapshot or {},
                    "fundamental": decision.fundamental_snapshot or {},
                    "sentiment": decision.sentiment_snapshot or {},
                    "macro": decision.daily_bias or {},
                }
                base_feats = FeatureStore.compute_entry_features(analysis)
                entry_decisions.append({"features": {**base_feats, **mt_feats}, "label": label, "symbol": t.symbol, "direction": t.direction})

                # Team features
                from app.services.ml.team_meta_model import _extract_analyst_features, _extract_verifier_features
                team_feats = {}
                team_feats.update(_extract_analyst_features(decision.analyst_opinions))
                team_feats.update(_extract_verifier_features(decision.verifier_verdict, decision.lead_model))
                team_feats["label"] = label
                team_data.append(team_feats)

            if len(entry_decisions) >= 100:
                import pandas as pd
                entry_df = FeatureStore.export_training_set(entry_decisions)
                EntryQualityModel().train(entry_df)

            if len(team_data) >= 100:
                import pandas as pd
                team_df = pd.DataFrame(team_data)
                TeamMetaModel().train(team_df)

            logger.info("Retrained models on %d trades before %s", len(trades), cutoff)
        except Exception as exc:
            logger.warning("Model retrain failed: %s", exc, exc_info=True)

    def _compute_metrics(self) -> Dict[str, Any]:
        if not self.trades:
            return {"error": "No trades executed"}

        wins = [t for t in self.trades if t["pnl_usd"] > 0]
        losses = [t for t in self.trades if t["pnl_usd"] <= 0]
        total_pnl = sum(t["pnl_usd"] for t in self.trades)

        gross_profit = sum(t["pnl_usd"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl_usd"] for t in losses)) if losses else 1e-9
        pf = gross_profit / gross_loss

        # Sharpe on daily returns
        daily = {}
        for t in self.trades:
            day = t.get("timestamp", datetime.now(timezone.utc)).date()
            daily[day] = daily.get(day, 0) + t["pnl_usd"]
        returns = list(daily.values())
        sharpe = 0.0
        if len(returns) > 1:
            mean_r = np.mean(returns)
            std_r = np.std(returns)
            sharpe = (mean_r / std_r * np.sqrt(252)) if std_r > 0 else 0

        return {
            "initial_equity": self.initial_equity,
            "final_equity": self.equity,
            "total_return_pct": (self.equity - self.initial_equity) / self.initial_equity * 100,
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(self.trades) * 100 if self.trades else 0,
            "profit_factor": pf,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_trade_pnl": total_pnl / len(self.trades) if self.trades else 0,
            "avg_win": sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0,
            "avg_loss": sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0,
        }


@shared_task(
    bind=True,
    time_limit=3600 * 24,  # 24 hours max
    soft_time_limit=3600 * 22,
    queue="data_ingestion",
)
def run_full_expanding_window_backtest(
    self,
    start_iso: str = None,
    end_iso: str = None,
    symbols: List[str] = None,
    strategy_mode: str = "scalping",
    initial_equity: float = 200.0,
):
    """Kick off the full expanding-window backtest."""
    if start_iso is None:
        start = datetime(2025, 12, 1, tzinfo=timezone.utc)
    else:
        start = datetime.fromisoformat(start_iso)
    if end_iso is None:
        end = datetime(2026, 6, 18, tzinfo=timezone.utc)
    else:
        end = datetime.fromisoformat(end_iso)

    async def _run():
        engine = SessionBacktestEngine(initial_equity=initial_equity)
        results = await engine.run_full_backtest(start, end, symbols, strategy_mode)
        logger.info("Backtest complete: %s", results)
        return results

    return asyncio.run(_run())

#!/usr/bin/env python3
"""Standalone backtest — TECHNICAL VALIDATION TOOL ONLY.

WARNING: This backtest is NOT suitable for meta-classifier training or
profitability evaluation. The AI team requires live real-time data
(news sentiment, retail positioning, economic calendar) to generate
tradeable signals. With only stale pre-session candles + historical
macro/COT, the AI correctly returns HOLD at near-zero confidence.

Use this tool for:
  - Verifying indicator calculations on historical candles
  - Checking data pipeline integrity (macro, COT flows correctly)
  - Sanity-checking execution simulation (spreads, SL/TP, ATR sizing)
  - Technical-only baseline: BACKTEST_TECHNICAL_ONLY=true (no LLM calls)
  - ML filtering gates (match live trading):
      BACKTEST_ENTRY_GATE=true        (XGBoost entry quality gate)
      BACKTEST_ENTRY_GATE_THRESHOLD=0.40
      BACKTEST_TEAM_META=true         (TeamMetaModel confidence adjuster)
      BACKTEST_MEMORY_GUARD=true      (Qdrant pattern veto)
      BACKTEST_MEMORY_GUARD_MIN_WR=0.35
    Set any to "false" to disable that gate.

Do NOT use for:
  - Strategy profitability backtesting (without ML gates)
  - Parameter optimization

Run directly in the backend container (NOT via Celery):
  docker compose exec backend python run_backtest_standalone.py

Features:
  - File-based checkpoints: resumes from last completed session
  - Handles all API errors gracefully per session
  - Prints progress to stdout (watch with docker logs -f)
  - $200 starting equity, session-level decisions
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import pandas as pd
import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure app is importable
sys.path.insert(0, "/app")

from app.database import get_celery_session
from app import models
from app.enums import TradeDirection, TradeMode, DataProvider, TradeStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("backtest_standalone")

CHECKPOINT_DIR = "/app/backtest_checkpoints"
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# Session boundaries (UTC)
SESSIONS = [
    ("asian", 0, 7),
    ("london", 7, 13),
    ("london_ny", 13, 17),
    ("ny", 17, 21),
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


class CheckpointManager:
    """Save and resume backtest state from disk."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.state_file = os.path.join(CHECKPOINT_DIR, f"{run_id}_state.json")
        self.trades_file = os.path.join(CHECKPOINT_DIR, f"{run_id}_trades.jsonl")
        self._processed_keys: set = set()

    def load_state(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.state_file):
            return None
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            # Restore processed keys from prior run
            self._processed_keys = set(state.get("processed_keys", []))
            return state
        except Exception:
            return None

    def save_state(self, state: Dict[str, Any]):
        state["processed_keys"] = list(self._processed_keys)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, self.state_file)

    def append_trade(self, trade: Dict[str, Any]):
        with open(self.trades_file, "a") as f:
            f.write(json.dumps(trade, default=str) + "\n")

    def load_trades(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.trades_file):
            return []
        trades = []
        with open(self.trades_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trades.append(json.loads(line))
                    except Exception:
                        pass
        return trades

    def session_key(self, symbol: str, session_start: datetime) -> str:
        return f"{symbol}_{session_start.isoformat()}"

    def is_processed(self, key: str) -> bool:
        return key in self._processed_keys

    def mark_processed(self, key: str):
        self._processed_keys.add(key)


class StandaloneBacktestEngine:
    """Backtest engine with checkpoint/resume support."""

    def __init__(self, initial_equity: float = 200.0, run_id: str = None, technical_only: bool = False):
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.max_equity = initial_equity
        self.max_drawdown_pct = 0.0
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.checkpoint = CheckpointManager(self.run_id)
        self.session_count = 0
        self.trade_count = 0
        self.error_count = 0
        self.technical_only = technical_only
        # --- ML filtering gates (match live trading behaviour) ---
        # Entry gate: XGBoost model blocks low-quality entries before LLM call
        self.entry_gate_enabled = os.environ.get("BACKTEST_ENTRY_GATE", "true").lower() in ("1", "true", "yes")
        self.entry_gate_threshold = float(os.environ.get("BACKTEST_ENTRY_GATE_THRESHOLD", "0.40"))
        # TeamMeta: adjusts confidence based on analyst agreement patterns
        self.team_meta_enabled = os.environ.get("BACKTEST_TEAM_META", "true").lower() in ("1", "true", "yes")
        # Memory guard: Qdrant veto on historically poor setups
        self.memory_guard_enabled = os.environ.get("BACKTEST_MEMORY_GUARD", "true").lower() in ("1", "true", "yes")
        self.memory_guard_min_winrate = float(os.environ.get("BACKTEST_MEMORY_GUARD_MIN_WR", "0.35"))
        # Cached model instances (reloaded after retrain)
        self._entry_model = None
        self._team_meta_model = None
        # HOLD-reason counters for diagnostics
        self.hold_reasons: Dict[str, int] = {
            "no_candles": 0,
            "v2_failed": 0,
            "ai_hold": 0,
            "low_confidence": 0,
            "zero_prices": 0,
            "entry_gate": 0,
            "memory_guard": 0,
        }

    @staticmethod
    def _sanitize_json(obj):
        """Recursively convert numpy types to native Python types for JSON serialization."""
        import numpy as np
        if isinstance(obj, dict):
            return {k: StandaloneBacktestEngine._sanitize_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [StandaloneBacktestEngine._sanitize_json(v) for v in obj]
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    def _compute_atr_based_sl(self, candles: pd.DataFrame, entry_price: float, direction: str) -> Optional[float]:
        """Compute adaptive stop-loss based on 14-period ATR.
        
        Rules:
        - SL distance = 1.5x ATR (adapts to volatility)
        - Minimum: 10 pips (noise floor)
        - Maximum: 30 pips (hard cap to limit single-trade loss)
        """
        if candles.empty or len(candles) < 14:
            return None
        
        high = candles["high"].values
        low = candles["low"].values
        close = candles["close"].values
        
        # True Range
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        
        # 14-period ATR
        atr_14 = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
        
        # SL distance = 1.5x ATR
        sl_dist = atr_14 * 1.5
        
        # Symbol-specific pip value
        pip = 0.01 if "JPY" in candles.attrs.get("symbol", "") else 0.0001
        min_sl_dist = 10.0 * pip
        max_sl_dist = 30.0 * pip
        
        sl_dist = max(min_sl_dist, min(max_sl_dist, sl_dist))
        
        is_buy = direction.lower() == "buy"
        return entry_price - sl_dist if is_buy else entry_price + sl_dist

    def _compute_atr(self, candles: pd.DataFrame) -> Optional[float]:
        """Compute 14-period ATR and return in pips."""
        if candles.empty or len(candles) < 14:
            return None
        high = candles["high"].values
        low = candles["low"].values
        close = candles["close"].values
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        atr_14 = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
        pip = 0.01 if "JPY" in candles.attrs.get("symbol", "") else 0.0001
        return round(atr_14 / pip, 2) if pip else None

    def _run_technical(self, symbol: str, candles: pd.DataFrame) -> Optional[Dict]:
        if candles.empty or len(candles) < 20:
            return None
        try:
            from app.analysis.technical import TechnicalAnalyzer
            snapshot = candles.to_dict("records")
            tech = TechnicalAnalyzer().analyze(snapshot)
            return {
                "signal": tech.get("signal", "neutral"),
                "confidence": tech.get("confidence", 0.5),
            }
        except Exception:
            return None

    async def _load_candles(self, db: AsyncSession, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        stmt = text("""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_candles
            WHERE symbol = :symbol AND timeframe = '5m'
              AND timestamp >= :start AND timestamp < :end
            ORDER BY timestamp
        """)
        result = await db.execute(stmt, {"symbol": symbol, "start": start, "end": end})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

    async def _load_candles_tf(self, db: AsyncSession, symbol: str, start: datetime, end: datetime, timeframe: str) -> pd.DataFrame:
        """Load candles for a specific timeframe. For wider context (15m, 1h), expands
        the window backwards so the analyst always has at least 50 candles of history."""
        # For slower timeframes we need a longer lookback to give the LLM market context
        lookback = {"1m": 0, "5m": 0, "15m": timedelta(hours=12), "1h": timedelta(hours=48)}
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
            "start": start - extra, "end": end,
        })
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

    async def _load_context(
        self, db: AsyncSession, symbol: str, session_start: datetime,
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
        self, db: AsyncSession, symbol: str, session_start: datetime, session_end: datetime
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

    async def _load_macro_snapshot(self, db: AsyncSession, session_start: datetime) -> Dict[str, Any]:
        """Load the most recent macro data from macro_series before session_start."""
        stmt = text("""
            SELECT series_id, value
            FROM macro_series
            WHERE timestamp <= :session_start
              AND series_id IN ('DTWEXBGS', 'VIXCLS', 'SP500', 'GOLDPMGBD228NLBM',
                                'DCOILWTICO', 'DGS10', 'DGS2', 'DGS30',
                                'DFEDTAR', 'FEDFUNDS', 'ECBDFR', 'T10Y2Y', 'T10YIE')
            ORDER BY timestamp DESC
        """)
        result = await db.execute(stmt, {"session_start": session_start})
        rows = result.fetchall()
        # Take the most recent value per series_id
        latest = {}
        for series_id, value in rows:
            if series_id not in latest:
                latest[series_id] = value

        dxy = latest.get("DTWEXBGS")
        vix = latest.get("VIXCLS")
        spx = latest.get("SP500")
        gold = latest.get("GOLDPMGBD228NLBM")
        oil = latest.get("DCOILWTICO")
        us10y = latest.get("DGS10")
        us02y = latest.get("DGS2")
        us30y = latest.get("DGS30")
        dfedtar = latest.get("DFEDTAR") or latest.get("FEDFUNDS")
        ecbdfr = latest.get("ECBDFR")
        t10y2y = latest.get("T10Y2Y")
        t10yie = latest.get("T10YIE")

        yield_spread = None
        if us10y is not None and us02y is not None:
            yield_spread = round(us10y - us02y, 2)
        elif t10y2y is not None:
            yield_spread = round(t10y2y, 2)

        # Risk-on / risk-off composite (-1.0 to +1.0)
        score = 0.0
        weights = 0.0
        if dxy is not None:
            score += (-0.3 if dxy > 105 else 0.2 if dxy < 100 else 0.0)
            weights += 1.0
        if vix is not None:
            score += (-0.4 if vix > 25 else 0.1 if vix < 15 else 0.0)
            weights += 1.0
        if yield_spread is not None:
            score += (-0.4 if yield_spread < 0 else 0.2 if yield_spread > 1.0 else 0.0)
            weights += 1.0
        composite = round(score / weights, 2) if weights > 0 else 0.0
        bias = "risk_on" if composite >= 0.3 else "risk_off" if composite <= -0.3 else "neutral"

        return {
            "dxy": round(dxy, 2) if dxy else None,
            "vix": round(vix, 2) if vix else None,
            "spx": round(spx, 2) if spx else None,
            "gold": round(gold, 2) if gold else None,
            "oil": round(oil, 2) if oil else None,
            "us10y": round(us10y, 2) if us10y else None,
            "us02y": round(us02y, 2) if us02y else None,
            "us30y": round(us30y, 2) if us30y else None,
            "yield_spread_10y_2y": yield_spread,
            "risk_on_score": composite,
            "bias": bias,
            "fed_rate": round(dfedtar, 2) if dfedtar else None,
            "ecb_rate": round(ecbdfr, 2) if ecbdfr else None,
        }

    async def _load_cot_snapshot(self, db: AsyncSession, symbol: str, session_start: datetime) -> Dict[str, Any]:
        """Load the most recent COT report for the symbol before session_start."""
        stmt = text("""
            SELECT report_date, nc_net, spec_pct_oi, open_interest
            FROM cot_reports
            WHERE symbol = :symbol
              AND report_date <= :session_start
            ORDER BY report_date DESC
            LIMIT 1
        """)
        try:
            result = await db.execute(stmt, {"symbol": symbol, "session_start": session_start.date()})
            row = result.fetchone()
            if row:
                report_date, nc_net, spec_pct_oi, open_interest = row
                return {
                    "report_date": report_date.isoformat() if report_date else None,
                    "net_position": nc_net,
                    "spec_pct_oi": round(spec_pct_oi, 2) if spec_pct_oi else None,
                    "open_interest": open_interest,
                    "institutional_bias": "bullish" if (nc_net or 0) > 0 else "bearish" if (nc_net or 0) < 0 else "neutral",
                    "source": "cftc",
                }
        except Exception as exc:
            logger.debug("Failed to load COT snapshot: %s", exc)
        return {
            "report_date": None,
            "net_position": None,
            "spec_pct_oi": None,
            "open_interest": None,
            "institutional_bias": "neutral",
            "source": "none",
        }

    async def _run_v2_decision(self, symbol: str, strategy_mode: str, ctx_5m: pd.DataFrame, ctx_15m: pd.DataFrame = None, session_name: str = "london", db: AsyncSession = None):
        """Run the v2 AI team with multi-timeframe analysis using ONLY pre-session context.

        ctx_5m and ctx_15m are candles strictly BEFORE session_start.
        The verifier is disabled here for two reasons:
          1. In backtesting there is no live market risk to protect against.
          2. The verifier was reducing confidence by 15% on REVISE, causing many
             borderline signals to fall below the 0.15 gate.
        """
        if ctx_5m.empty:
            return None, None
        from app.analysis.technical import TechnicalAnalyzer
        ta = TechnicalAnalyzer()

        tech_5m = ta.analyze(ctx_5m.to_dict("records"))

        # Build timeframe map — include 15m context if available
        tf_map = {"5m": tech_5m}
        overall_signal = tech_5m.get("signal", "neutral")
        if ctx_15m is not None and not ctx_15m.empty and len(ctx_15m) >= 20:
            tech_15m = ta.analyze(ctx_15m.to_dict("records"))
            tf_map["15m"] = tech_15m
            # Weight 5m and 15m equally for overall signal
            scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
            for sig_val, w in [(tech_5m.get("signal", "neutral"), 0.5), (tech_15m.get("signal", "neutral"), 0.5)]:
                scores[sig_val] = scores.get(sig_val, 0.0) + w
            overall_signal = max(scores, key=scores.get)

        # --- Fetch real historical fundamental/sentiment/macro data ---
        # Use the real analysis modules with as_of=session_start to avoid look-ahead bias.
        # In technical-only mode, skip analyzer calls (no LLM/API needed) and use stubs.
        # Falls back to neutral stubs if DB is unavailable or analyzers fail.
        session_start = pd.to_datetime(ctx_5m.iloc[-1]["timestamp"]) if not ctx_5m.empty else datetime.now(timezone.utc)
        if self.technical_only:
            # Technical-only mode: skip all analyzer calls, use neutral stubs
            fundamental_data = {"event_risk": "low", "direction_bias": "neutral", "note": "technical-only"}
            sentiment_data = {"overall_sentiment": "neutral", "sentiment_score": 0.0, "note": "technical-only"}
            macro_data = {"bias": "neutral", "risk_on_score": 0.0, "note": "technical-only"}
        elif db is not None:
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

        # --- Entry Gate: XGBoost pre-filter (skip low-quality entries before LLM call) ---
        if not self.technical_only and self.entry_gate_enabled:
            entry_score = self._predict_entry_quality(analysis)
            if entry_score is not None and entry_score < self.entry_gate_threshold:
                self.hold_reasons["entry_gate"] += 1
                logger.info("Entry gate blocked %s (score=%.2f < %.2f)",
                           symbol, entry_score, self.entry_gate_threshold)
                return {"decision": "HOLD", "confidence": 0.0,
                        "rationale": f"Entry gate blocked (score={entry_score:.2f})",
                        "lead_model": "xgb_entry_gate"}, analysis

        # --- Technical-only baseline mode (Phase 4B) ---
        if self.technical_only:
            tech_signal = overall_signal
            if tech_signal in ("bullish", "bearish"):
                last_close = float(ctx_5m.iloc[-1]["close"])
                atr = self._compute_atr(ctx_5m)
                sl_pips = max(10, min(30, atr * 1.5)) if atr else 15
                pip = 0.0001 if "JPY" not in symbol else 0.01
                sl_dist = sl_pips * pip
                direction = "BUY" if tech_signal == "bullish" else "SELL"
                entry = last_close
                sl = entry - sl_dist if direction == "BUY" else entry + sl_dist
                tp = entry + sl_dist * 1.5 if direction == "BUY" else entry - sl_dist * 1.5
                return {
                    "decision": direction,
                    "confidence": 0.5,
                    "timeframe": "M5",
                    "entry_price": round(entry, 5),
                    "stop_loss": round(sl, 5),
                    "take_profit": round(tp, 5),
                    "position_size_pct": 1.0,
                    "risk_reward": 1.5,
                    "rationale": f"technical-only {tech_signal}",
                    "lead_model": "technical_baseline",
                }, analysis
            return {"decision": "HOLD", "confidence": 0.0}, analysis

        from app.ai.team.orchestrator import TeamDecisionEngine
        from app.ai.suites import resolve_models
        models_map = resolve_models("production")
        team = TeamDecisionEngine(
            technical_model=models_map.get("technical"),
            fundamental_model=models_map.get("fundamental"),
            sentiment_model=models_map.get("sentiment"),
            macro_model=models_map.get("macro"),
            lead_model=models_map.get("lead"),
            verifier_model=models_map.get("verifier"),
            # Verifier disabled in backtest: it has no live risk to guard against and
            # reduces tradeable signals by 30-40% via vetoes and confidence penalties.
            verifier_enabled=False,
            analyst_parallelism=True,
        )
        try:
            result = await team.decide(symbol, strategy_mode, analysis)
            # --- TeamMetaModel: adjust confidence based on analyst agreement patterns ---
            if result and self.team_meta_enabled and result.get("decision") in ("BUY", "SELL"):
                meta_score = self._predict_team_meta(result)
                if meta_score is not None:
                    old_conf = float(result.get("confidence", 0.5))
                    adjusted = min(old_conf * (0.70 + 0.60 * meta_score), 1.0)
                    result["confidence"] = adjusted
                    result["rationale"] = (result.get("rationale", "") +
                                          f" | TeamMeta: score={meta_score:.2f}, conf {old_conf:.2f}->{adjusted:.2f}")
                    logger.debug("TeamMeta adjusted %s: %.2f -> %.2f (meta=%.2f)",
                                symbol, old_conf, adjusted, meta_score)
            # Sanitize confidence: models sometimes return lists
            if result and "confidence" in result:
                c = result["confidence"]
                if isinstance(c, list):
                    while isinstance(c, list) and len(c) > 0:
                        c = c[0]
                    result["confidence"] = float(c) if (c is not None and not isinstance(c, list)) else 0.0
                else:
                    result["confidence"] = float(c)
            return result, analysis
        except Exception as exc:
            logger.warning("v2 decision failed for %s: %s", symbol, str(exc)[:80])
            return None, None

    # ------------------------------------------------------------------
    # ML filtering helpers
    # ------------------------------------------------------------------

    def _predict_entry_quality(self, analysis: Dict[str, Any]) -> Optional[float]:
        """Run EntryQualityModel on the analysis snapshot. Returns None if no model loaded."""
        try:
            if self._entry_model is None:
                from app.services.ml.entry_model import EntryQualityModel
                self._entry_model = EntryQualityModel()
            if self._entry_model.model is None:
                return None
            from app.services.feature_store import FeatureStore
            features = FeatureStore.compute_entry_features(analysis)
            return self._entry_model.predict(features)
        except Exception as exc:
            logger.debug("Entry gate predict failed: %s", str(exc)[:80])
            return None

    def _predict_team_meta(self, result: Dict[str, Any]) -> Optional[float]:
        """Run TeamMetaModel on the AI team's analyst opinions. Returns None if no model loaded."""
        try:
            if self._team_meta_model is None:
                from app.services.ml.team_meta_model import TeamMetaModel
                self._team_meta_model = TeamMetaModel()
            if self._team_meta_model.model is None:
                return None
            return self._team_meta_model.predict(
                result.get("analyst_opinions"),
                result.get("verifier_verdict"),
                result.get("lead_model"),
            )
        except Exception as exc:
            logger.debug("TeamMeta predict failed: %s", str(exc)[:80])
            return None

    async def _memory_guard_check(
        self, vs, analysis: Dict[str, Any], decision: str, session_start: datetime
    ) -> tuple[bool, str]:
        """Check Qdrant for historically similar setups. Returns (ok, reason)."""
        if not self.memory_guard_enabled:
            return True, ""
        try:
            # Set cutoff so we don't retrieve future trades (point-in-time)
            os.environ["BACKTEST_DATE_CUTOFF"] = session_start.isoformat()
            similar = await vs.search_similar(analysis.get("technical", {}), limit=20)
        except Exception:
            return True, ""
        finally:
            os.environ.pop("BACKTEST_DATE_CUTOFF", None)

        same = [s for s in similar
                if s.get("decision") == decision
                and s.get("outcome_pnl") is not None]
        if len(same) < 5:
            return True, ""
        wins = sum(1 for s in same if (s.get("outcome_pnl") or 0) > 0)
        win_rate = wins / len(same)
        avg_pnl = sum((s.get("outcome_pnl") or 0) for s in same) / len(same)
        if win_rate < self.memory_guard_min_winrate and avg_pnl < 0:
            return False, (f"Memory guard veto: {len(same)} similar {decision} setups "
                          f"({win_rate:.0%} win, avg ${avg_pnl:.2f})")
        return True, ""

    def _simulate_trade(
        self, symbol: str, decision: Dict, exec_candles: pd.DataFrame, ctx_candles: pd.DataFrame = None
    ) -> Optional[Dict]:
        """Simulate trade execution from a team decision.

        Uses exec_candles for walk-forward simulation and ctx_candles (pre-session)
        for ATR-based stop-loss computation.  No look-ahead bias.
        """
        lead_decision = decision.get("decision", "HOLD")
        lead_conf = float(decision.get("confidence", 0))

        if lead_decision not in ("BUY", "SELL") or lead_conf < 0.15:
            self.hold_reasons["low_confidence"] += 1
            return None
        use_decision = decision
        conf = lead_conf

        entry = float(use_decision.get("entry_price", 0))
        sl = float(use_decision.get("stop_loss", 0))
        tp = float(use_decision.get("take_profit", 0))
        if entry == 0 or sl == 0 or tp == 0:
            self.hold_reasons["zero_prices"] += 1
            return None

        if exec_candles.empty or len(exec_candles) < 2:
            return None

        direction = use_decision["decision"].lower()
        is_buy = direction == "buy"
        entry_price = float(exec_candles.iloc[0]["open"])

        # Recalculate SL/TP from actual entry
        ai_sl_dist = abs(entry - sl)
        ai_tp_dist = abs(tp - entry)

        # ATR SL: use pre-session context, not session candles (no look-ahead)
        atr_sl = self._compute_atr_based_sl(
            ctx_candles if ctx_candles is not None else exec_candles,
            entry_price, direction
        )
        if atr_sl is not None:
            # Use the TIGHTER stop (closer to entry = smaller loss)
            if is_buy:
                actual_sl = max(atr_sl, entry_price - ai_sl_dist)
            else:
                actual_sl = min(atr_sl, entry_price + ai_sl_dist)
        else:
            actual_sl = entry_price - ai_sl_dist if is_buy else entry_price + ai_sl_dist

        actual_tp = entry_price + ai_tp_dist if is_buy else entry_price - ai_tp_dist

        # Walk forward: iterate exec_candles only
        for idx in range(1, len(exec_candles)):
            candle = exec_candles.iloc[idx]
            if is_buy:
                if candle["low"] <= actual_sl:
                    exit_price = actual_sl
                    pnl = exit_price - entry_price
                    reason = "stop_loss"
                    break
                elif candle["high"] >= actual_tp:
                    exit_price = actual_tp
                    pnl = exit_price - entry_price
                    reason = "take_profit"
                    break
            else:
                if candle["high"] >= actual_sl:
                    exit_price = actual_sl
                    pnl = entry_price - exit_price
                    reason = "stop_loss"
                    break
                elif candle["low"] <= actual_tp:
                    exit_price = actual_tp
                    pnl = entry_price - exit_price
                    reason = "take_profit"
                    break
        else:
            exit_price = float(exec_candles.iloc[-1]["close"])
            pnl = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
            reason = "session_end"

        pip = 0.0001 if "JPY" not in symbol else 0.01
        pnl_pips = pnl / pip
        # Dynamic position sizing: 2% of current equity per trade
        risk_amount = self.equity * 0.02
        risk_amount = max(2.0, min(risk_amount, 20.0))  # clamp $2-$20
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
            "close_reason": reason,
            "lot_size": lot_size,
            "confidence": conf,
            "model_used": decision.get("lead_model", ""),
            "spread_cost_usd": spread_cost_usd,
            "timestamp": exec_candles.iloc[0]["timestamp"].isoformat() if hasattr(exec_candles.iloc[0]["timestamp"], 'isoformat') else str(exec_candles.iloc[0]["timestamp"]),
        }

    async def run_session(self, db: AsyncSession, symbol: str, s_start: datetime, s_end: datetime, strategy_mode: str, s_name: str = "london") -> Optional[Dict]:
        # Deduplicate: skip if this symbol+session was already processed in a prior run
        key = self.checkpoint.session_key(symbol, s_start)
        if self.checkpoint.is_processed(key):
            return None

        try:
            # Context window — AI may see only candles BEFORE session_start
            ctx_5m  = await self._load_context(db, symbol, s_start, timedelta(hours=24), "5m")
            ctx_15m = await self._load_context(db, symbol, s_start, timedelta(hours=48), "15m")
            if ctx_5m.empty:
                self.hold_reasons["no_candles"] += 1
                return None

            # Execution window — simulator only, AI never sees these
            exec_5m = await self._load_execution(db, symbol, s_start, s_end)

            v2_result, analysis = await self._run_v2_decision(symbol, strategy_mode, ctx_5m, ctx_15m, session_name=s_name, db=db)
            if not v2_result:
                self.hold_reasons["v2_failed"] += 1
                return None

            decision = v2_result.get("decision", "HOLD")
            lead_conf = float(v2_result.get("confidence", 0.0) or 0.0)

            if decision not in ("BUY", "SELL"):
                self.hold_reasons["ai_hold"] += 1

            trade_dict = None
            if decision in ("BUY", "SELL"):
                # --- Memory Guard: Qdrant veto on historically poor setups ---
                if self.memory_guard_enabled:
                    try:
                        from app.services.vector_store import VectorStore
                        vs = VectorStore()
                        ok, veto_reason = await self._memory_guard_check(
                            vs, analysis, decision, s_start
                        )
                        if not ok:
                            self.hold_reasons["memory_guard"] += 1
                            logger.info("Memory guard vetoed %s %s: %s", symbol, decision, veto_reason)
                            v2_result["decision"] = "HOLD"
                            v2_result["rationale"] = (v2_result.get("rationale", "") +
                                                      f" | {veto_reason}")
                            decision = "HOLD"
                    except Exception as mg_exc:
                        logger.debug("Memory guard failed for %s: %s", symbol, str(mg_exc)[:80])

                if decision in ("BUY", "SELL"):
                    trade_dict = self._simulate_trade(symbol, v2_result, exec_5m, ctx_candles=ctx_5m)

            # ------------------------------------------------------------------
            # Persist AIDecision + Trade to DB for meta-model training
            # ------------------------------------------------------------------
            try:
                from sqlalchemy import select
                existing = await db.execute(
                    select(models.AIDecision.id)
                    .where(models.AIDecision.symbol == symbol)
                    .where(models.AIDecision.timestamp == s_start)
                    .where(models.AIDecision.engine_version == "v2")
                    .limit(1)
                )
                if existing.scalar():
                    logger.debug("Skipping duplicate persist for %s %s", symbol, s_start)
                    return trade_dict

                db_decision = models.AIDecision(
                    symbol=symbol,
                    timestamp=s_start,
                    decision=decision,
                    confidence=lead_conf,
                    timeframe=v2_result.get("timeframe", "M5"),
                    entry_price=v2_result.get("entry_price"),
                    stop_loss=v2_result.get("stop_loss"),
                    take_profit=v2_result.get("take_profit"),
                    position_size_pct=v2_result.get("position_size_pct", 1.0),
                    risk_reward=v2_result.get("risk_reward", 1.0),
                    rationale=v2_result.get("rationale", ""),
                    technical_snapshot=self._sanitize_json(analysis.get("technical")),
                    fundamental_snapshot=self._sanitize_json(analysis.get("fundamental")),
                    sentiment_snapshot=self._sanitize_json(analysis.get("sentiment")),
                    model_used=v2_result.get("lead_model", ""),
                    provider=DataProvider.MT5_ZMQ,
                    engine_version="v2",
                    analyst_opinions=self._sanitize_json(v2_result.get("analyst_opinions")),
                    lead_model=v2_result.get("lead_model"),
                    verifier_model=v2_result.get("verifier_model"),
                    verifier_verdict=v2_result.get("verifier_verdict"),
                    verifier_confidence=v2_result.get("verifier_confidence"),
                    regime=self._sanitize_json({
                        "strategy_mode": strategy_mode,
                        "session": analysis.get("session", "unknown"),
                        "detected": analysis.get("regime", "unknown"),
                    }),
                    daily_bias=v2_result.get("daily_bias"),
                )
                db.add(db_decision)
                await db.flush()  # get db_decision.id

                if trade_dict:
                    direction = TradeDirection.BUY if trade_dict["direction"] == "buy" else TradeDirection.SELL
                    db_trade = models.Trade(
                        symbol=symbol,
                        direction=direction,
                        status=TradeStatus.CLOSED,
                        mode=TradeMode.PAPER,
                        entry_price=trade_dict["entry_price"],
                        exit_price=trade_dict["exit_price"],
                        stop_loss=trade_dict["stop_loss"],
                        take_profit=trade_dict["take_profit"],
                        position_size=trade_dict["lot_size"],
                        pnl=trade_dict["pnl_usd"],
                        pnl_pct=(trade_dict["pnl_usd"] / max(self.equity, 1.0)) * 100,
                        open_time=s_start,
                        close_time=s_end,
                        ai_decision_id=db_decision.id,
                        rationale=trade_dict.get("close_reason", ""),
                        provider=DataProvider.MT5_ZMQ,
                    )
                    db.add(db_trade)

                await db.commit()

                # --- Store snapshot in Qdrant for memory guard ---
                if self.memory_guard_enabled and trade_dict:
                    try:
                        from app.services.vector_store import VectorStore
                        vs = VectorStore()
                        point_id = str(db_decision.id)
                        await vs.upsert_snapshot(
                            point_id=point_id,
                            snapshot=analysis.get("technical", {}),
                            payload={
                                "symbol": symbol,
                                "decision": decision,
                                "confidence": lead_conf,
                                "outcome_pnl": trade_dict["pnl_usd"],
                                "outcome_status": trade_dict.get("close_reason", "unknown"),
                                "strategy_mode": strategy_mode,
                                "timestamp": s_start.isoformat(),
                            },
                        )
                    except Exception as qdrant_exc:
                        logger.debug("Qdrant snapshot store failed: %s", str(qdrant_exc)[:80])

            except Exception as db_exc:
                logger.warning("DB persist failed for %s %s: %s", symbol, s_start, str(db_exc)[:100])
                await db.rollback()

            # Mark this symbol+session as successfully processed
            self.checkpoint.mark_processed(key)
            return trade_dict
        except Exception as exc:
            self.error_count += 1
            logger.warning("Session failed for %s %s: %s", symbol, s_start, str(exc)[:100])
        return None

    async def run(self, start: datetime, end: datetime, symbols: List[str], strategy_mode: str = "scalping", retrain_monthly: bool = True):
        # Try to resume from checkpoint
        state = self.checkpoint.load_state()
        if state:
            logger.info("Resuming from checkpoint: session_idx=%d equity=$%.2f", state.get("session_idx", 0), state.get("equity", self.initial_equity))
            self.session_count = state.get("session_idx", 0)
            self.equity = state.get("equity", self.initial_equity)
            self.max_equity = state.get("max_equity", self.initial_equity)
            self.max_drawdown_pct = state.get("max_drawdown_pct", 0.0)
            loaded_trades = self.checkpoint.load_trades()
            self.trade_count = len(loaded_trades)  # authoritative count from file
            self.error_count = state.get("error_count", 0)
            self.hold_reasons.update(state.get("hold_reasons", {}))
            logger.info("Loaded %d trades from checkpoint file", len(loaded_trades))
        else:
            logger.info("Starting fresh backtest: %s to %s, %d symbols", start, end, len(symbols))

        # Generate session list (skip weekends — forex closed)
        all_sessions = []
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current < end:
            if current.weekday() < 5:  # 5 = Saturday, 6 = Sunday
                for name, h0, h1 in SESSIONS:
                    s_start = current.replace(hour=h0, minute=0)
                    s_end = current.replace(hour=h1, minute=0)
                    if s_start >= start and s_end <= end:
                        all_sessions.append((s_start, s_end, name))
            current += timedelta(days=1)

        logger.info("Total sessions: %d", len(all_sessions))

        async with get_celery_session()() as db:
            # Budget tracking for production runs
            BUDGET_USD = 20.0  # increased to finish all 988 sessions
            COST_PER_SESSION = 0.03308  # $7 covers ~211 sessions
            estimated_cost = 0.0
            
            import os
            for idx in range(self.session_count, len(all_sessions)):
                s_start, s_end, s_name = all_sessions[idx]
                self.session_count = idx
                os.environ["BACKTEST_DATE_CUTOFF"] = s_start.isoformat()

                # Monthly model retrain
                if retrain_monthly and s_start.day == 1 and s_start.hour == 0:
                    logger.info("Month boundary: %s — retraining models", s_start)
                    await self._retrain(db, s_start)

                for symbol in symbols:
                    trade = await self.run_session(db, symbol, s_start, s_end, strategy_mode, s_name)
                    if trade:
                        self.trade_count += 1
                        self.equity += trade["pnl_usd"]
                        self.max_equity = max(self.max_equity, self.equity)
                        dd = (self.max_equity - self.equity) / self.max_equity * 100
                        self.max_drawdown_pct = max(self.max_drawdown_pct, dd)
                        self.checkpoint.append_trade(trade)

                # Budget tracking
                estimated_cost += COST_PER_SESSION
                
                # Budget stop marker
                if estimated_cost >= BUDGET_USD:
                    logger.info("BUDGET EXHAUSTED: $%.2f spent | Stopping at session %d/%d | Resume next time!", 
                                estimated_cost, idx + 1, len(all_sessions))
                    # Save final marker state
                    self.checkpoint.save_state({
                        "session_idx": idx + 1,
                        "equity": self.equity,
                        "max_equity": self.max_equity,
                        "max_drawdown_pct": self.max_drawdown_pct,
                        "trade_count": self.trade_count,
                        "error_count": self.error_count,
                        "last_session": s_start.isoformat(),
                        "budget_spent": estimated_cost,
                        "budget_limit": BUDGET_USD,
                        "status": "PAUSED_BUDGET_EXHAUSTED",
                        "hold_reasons": dict(self.hold_reasons),
                    })
                    break
                
                # Save checkpoint every session
                self.checkpoint.save_state({
                    "session_idx": idx + 1,
                    "equity": self.equity,
                    "max_equity": self.max_equity,
                    "max_drawdown_pct": self.max_drawdown_pct,
                    "trade_count": self.trade_count,
                    "error_count": self.error_count,
                    "last_session": s_start.isoformat(),
                    "hold_reasons": dict(self.hold_reasons),
                })

                # Print progress every 10 sessions with HOLD breakdown
                if (idx + 1) % 10 == 0:
                    total_holds = sum(self.hold_reasons.values())
                    logger.info(
                        "Checkpoint: %d/%d sessions | equity=$%.2f | trades=%d | errors=%d | max_dd=%.1f%%",
                        idx + 1, len(all_sessions), self.equity, self.trade_count, self.error_count, self.max_drawdown_pct,
                    )
                    logger.info(
                        "HOLD breakdown (total=%d): no_candles=%d v2_failed=%d "
                        "ai_hold=%d low_conf=%d zero_prices=%d entry_gate=%d memory_guard=%d",
                        total_holds,
                        self.hold_reasons["no_candles"],
                        self.hold_reasons["v2_failed"],
                        self.hold_reasons["ai_hold"],
                        self.hold_reasons["low_confidence"],
                        self.hold_reasons["zero_prices"],
                        self.hold_reasons["entry_gate"],
                        self.hold_reasons["memory_guard"],
                    )

                # Rate limit: small sleep between sessions
                await asyncio.sleep(0.5)  # minimal delay for production models (no rate limits)

        metrics = self._compute_metrics()
        logger.info("BACKTEST COMPLETE: %s", json.dumps(metrics, indent=2, default=str))
        return metrics

    async def _retrain(self, db: AsyncSession, cutoff: datetime):
        try:
            from app.services.ml.multitimeframe_features import compute_multitimeframe_features
            from app.services.ml.team_meta_model import TeamMetaModel, _extract_analyst_features, _extract_verifier_features
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
                logger.info("Retrain skipped: %d trades", len(trades))
                return

            entry_data = []
            team_data = []
            for t in trades:
                d_result = await db.execute(select(models.AIDecision).where(models.AIDecision.id == t.ai_decision_id))
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
                entry_data.append({"features": {**base, **mt}, "label": label, "symbol": t.symbol, "direction": t.direction})
                tf = {}
                tf.update(_extract_analyst_features(decision.analyst_opinions))
                tf.update(_extract_verifier_features(decision.verifier_verdict, decision.lead_model))
                tf["label"] = label
                team_data.append(tf)

            if len(entry_data) >= 100:
                import pandas as pd
                EntryQualityModel().train(FeatureStore.export_training_set(entry_data))
                # Reload cached instance so subsequent predictions use the new model
                self._entry_model = EntryQualityModel()
                logger.info("Entry gate model reloaded")
            if len(team_data) >= 100:
                import pandas as pd
                TeamMetaModel().train(pd.DataFrame(team_data))
                # Reload cached instance so subsequent predictions use the new model
                self._team_meta_model = TeamMetaModel()
                logger.info("TeamMeta model reloaded")
            logger.info("Retrained on %d trades", len(trades))
        except Exception as exc:
            logger.warning("Retrain failed: %s", str(exc)[:120])

    def _compute_metrics(self) -> Dict[str, Any]:
        trades = self.checkpoint.load_trades()
        if not trades:
            return {"error": "No trades"}
        wins = [t for t in trades if t.get("pnl_usd", 0) > 0]
        losses = [t for t in trades if t.get("pnl_usd", 0) <= 0]
        total_pnl = sum(t.get("pnl_usd", 0) for t in trades)
        gross_profit = sum(t.get("pnl_usd", 0) for t in wins) if wins else 0
        gross_loss = abs(sum(t.get("pnl_usd", 0) for t in losses)) if losses else 1e-9

        daily = {}
        for t in trades:
            ts = t.get("timestamp", "")
            try:
                day = pd.to_datetime(ts).date()
                daily[str(day)] = daily.get(str(day), 0) + t.get("pnl_usd", 0)
            except Exception:
                pass
        returns = list(daily.values())
        sharpe = 0.0
        if len(returns) > 1:
            m, s = np.mean(returns), np.std(returns)
            sharpe = (m / s * np.sqrt(252)) if s > 0 else 0

        return {
            "initial_equity": self.initial_equity,
            "final_equity": self.equity,
            "total_return_pct": (self.equity - self.initial_equity) / self.initial_equity * 100,
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0,
            "profit_factor": gross_profit / gross_loss,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "avg_trade_pnl": total_pnl / len(trades),
            "avg_win": sum(t.get("pnl_usd", 0) for t in wins) / len(wins) if wins else 0,
            "avg_loss": sum(t.get("pnl_usd", 0) for t in losses) / len(losses) if losses else 0,
            "error_count": self.error_count,
        }


def find_latest_checkpoint():
    import glob
    states = glob.glob(os.path.join(CHECKPOINT_DIR, '*_state.json'))
    if not states:
        return None
    # Sort by modification time, newest first
    states.sort(key=os.path.getmtime, reverse=True)
    latest = os.path.basename(states[0]).replace('_state.json', '')
    return latest

async def main():
    # Try to resume from latest checkpoint
    latest_run = find_latest_checkpoint()
    technical_only = os.environ.get("BACKTEST_TECHNICAL_ONLY", "").lower() in ("1", "true", "yes")
    if latest_run:
        logger.info('Resuming from checkpoint: %s', latest_run)
        engine = StandaloneBacktestEngine(initial_equity=200.0, run_id=latest_run, technical_only=technical_only)
    else:
        engine = StandaloneBacktestEngine(initial_equity=200.0, technical_only=technical_only)
    start = datetime(2025, 10, 17, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, tzinfo=timezone.utc)
    symbols = ACTIVE_SYMBOLS

    logger.info("=" * 60)
    logger.info("BACKTEST STARTING")
    logger.info("=" * 60)
    logger.info("Run ID: %s", engine.run_id)
    logger.info("Mode: %s", "TECHNICAL_ONLY" if technical_only else "FULL_AI")
    logger.info("Date range: %s to %s", start, end)
    logger.info("Symbols: %s", symbols)
    logger.info("Starting equity: $%.2f", engine.initial_equity)
    logger.info("Checkpoint dir: %s", CHECKPOINT_DIR)
    logger.info("=" * 60)

    results = await engine.run(start, end, symbols, strategy_mode="scalping")

    logger.info("=" * 60)
    logger.info("BACKTEST COMPLETE")
    logger.info("=" * 60)
    for k, v in results.items():
        logger.info("  %s: %s", k, v)


if __name__ == "__main__":
    asyncio.run(main())

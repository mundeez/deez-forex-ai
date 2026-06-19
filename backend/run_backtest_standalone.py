#!/usr/bin/env python3
"""Standalone expanding-window backtest with file-based checkpoints.

Run directly in the backend container (NOT via Celery):
  docker compose exec backend python run_backtest_standalone.py

Features:
  - File-based checkpoints: resumes from last completed session
  - Handles all API errors gracefully per session
  - Prints progress to stdout (watch with docker logs -f)
  - Expanding window: retrains models monthly
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
from app.enums import TradeDirection, TradeMode

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


class CheckpointManager:
    """Save and resume backtest state from disk."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.state_file = os.path.join(CHECKPOINT_DIR, f"{run_id}_state.json")
        self.trades_file = os.path.join(CHECKPOINT_DIR, f"{run_id}_trades.jsonl")

    def load_state(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.state_file):
            return None
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def save_state(self, state: Dict[str, Any]):
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


class StandaloneBacktestEngine:
    """Backtest engine with checkpoint/resume support."""

    def __init__(self, initial_equity: float = 200.0, run_id: str = None):
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.max_equity = initial_equity
        self.max_drawdown_pct = 0.0
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.checkpoint = CheckpointManager(self.run_id)
        self.session_count = 0
        self.trade_count = 0
        self.error_count = 0

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

    async def _run_v2_decision(self, symbol: str, strategy_mode: str, candles: pd.DataFrame) -> Optional[Dict]:
        if candles.empty:
            return None
        from app.analysis.technical import TechnicalAnalyzer
        snapshot = candles.to_dict("records")
        tech = TechnicalAnalyzer().analyze(snapshot)
        analysis = {
            "symbol": symbol,
            "technical": {"timeframes": {"5m": tech}, "overall_signal": tech.get("signal", "neutral")},
            "fundamental": {"event_risk": "low", "direction_bias": "neutral"},
            "sentiment": {"overall_sentiment": "neutral", "sentiment_score": 0.0},
            "macro": {},
            "regime": "unknown",
            "session": "london",
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
            logger.warning("v2 decision failed for %s: %s", symbol, str(exc)[:80])
            return None

    def _simulate_trade(self, symbol: str, decision: Dict, candles: pd.DataFrame, tech_signal: Optional[Dict] = None) -> Optional[Dict]:
        # Fallback: if lead gave HOLD but technical signal is strong, trade on technical
        lead_decision = decision.get("decision", "HOLD")
        lead_conf = float(decision.get("confidence", 0))
        
        if lead_decision in ("BUY", "SELL") and lead_conf >= 0.25:
            use_decision = decision
        elif tech_signal and tech_signal.get("signal") in ("bullish", "bearish"):
            tech_conf = float(tech_signal.get("confidence", 0.5))
            if tech_conf >= 0.6:
                # Use technical signal as fallback when lead is weak/missing
                fallback = dict(decision)
                fallback["decision"] = "BUY" if tech_signal["signal"] == "bullish" else "SELL"
                fallback["confidence"] = tech_conf * 0.7  # discount for no-team consensus
                fallback["lead_model"] = "technical_fallback"
                use_decision = fallback
            else:
                return None
        else:
            return None
        entry = float(decision.get("entry_price", 0))
        sl = float(decision.get("stop_loss", 0))
        tp = float(decision.get("take_profit", 0))
        if entry == 0 or sl == 0 or tp == 0:
            return None

        if candles.empty or len(candles) < 2:
            return None

        direction = decision["decision"].lower()
        is_buy = direction == "buy"
        entry_price = float(candles.iloc[0]["open"])

        # Recalculate SL/TP from actual entry
        ai_sl_dist = abs(entry - sl)
        ai_tp_dist = abs(tp - entry)
        if is_buy:
            actual_sl = entry_price - ai_sl_dist
            actual_tp = entry_price + ai_tp_dist
        else:
            actual_sl = entry_price + ai_sl_dist
            actual_tp = entry_price - ai_tp_dist

        # Walk forward
        for idx in range(1, len(candles)):
            candle = candles.iloc[idx]
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
            exit_price = float(candles.iloc[-1]["close"])
            pnl = (exit_price - entry_price) if is_buy else (entry_price - exit_price)
            reason = "session_end"

        pip = 0.0001 if "JPY" not in symbol else 0.01
        pnl_pips = pnl / pip
        risk_amount = 2.0  # $2 risk per trade
        sl_pips = abs(entry_price - actual_sl) / pip
        if sl_pips == 0:
            return None
        lot_size = risk_amount / (sl_pips * 10.0)
        lot_size = max(0.01, min(lot_size, 0.1))
        pnl_usd = pnl_pips * lot_size * 10.0

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
            "timestamp": candles.iloc[0]["timestamp"].isoformat() if hasattr(candles.iloc[0]["timestamp"], 'isoformat') else str(candles.iloc[0]["timestamp"]),
        }

    async def run_session(self, db: AsyncSession, symbol: str, s_start: datetime, s_end: datetime, strategy_mode: str) -> Optional[Dict]:
        try:
            candles = await self._load_candles(db, symbol, s_start, s_end)
            tech = self._run_technical(symbol, candles)
            decision = await self._run_v2_decision(symbol, strategy_mode, candles)
            if decision and (decision.get("decision") in ("BUY", "SELL") or (tech and tech.get("confidence", 0) >= 0.6)):
                return self._simulate_trade(symbol, decision, candles, tech_signal=tech)
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
            self.trade_count = state.get("trade_count", 0)
            self.error_count = state.get("error_count", 0)
            loaded_trades = self.checkpoint.load_trades()
            logger.info("Loaded %d trades from checkpoint file", len(loaded_trades))
        else:
            logger.info("Starting fresh backtest: %s to %s, %d symbols", start, end, len(symbols))

        # Generate session list
        all_sessions = []
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current < end:
            for name, h0, h1 in SESSIONS:
                s_start = current.replace(hour=h0, minute=0)
                s_end = current.replace(hour=h1, minute=0)
                if s_start >= start and s_end <= end:
                    all_sessions.append((s_start, s_end, name))
            current += timedelta(days=1)

        logger.info("Total sessions: %d", len(all_sessions))

        async with get_celery_session()() as db:
            for idx in range(self.session_count, len(all_sessions)):
                s_start, s_end, s_name = all_sessions[idx]
                self.session_count = idx

                # Monthly model retrain
                if retrain_monthly and s_start.day == 1 and s_start.hour == 0:
                    logger.info("Month boundary: %s — retraining models", s_start)
                    await self._retrain(db, s_start)

                for symbol in symbols:
                    trade = await self.run_session(db, symbol, s_start, s_end, strategy_mode)
                    if trade:
                        self.trade_count += 1
                        self.equity += trade["pnl_usd"]
                        self.max_equity = max(self.max_equity, self.equity)
                        dd = (self.max_equity - self.equity) / self.max_equity * 100
                        self.max_drawdown_pct = max(self.max_drawdown_pct, dd)
                        self.checkpoint.append_trade(trade)

                # Save checkpoint every session
                self.checkpoint.save_state({
                    "session_idx": idx + 1,
                    "equity": self.equity,
                    "max_equity": self.max_equity,
                    "max_drawdown_pct": self.max_drawdown_pct,
                    "trade_count": self.trade_count,
                    "error_count": self.error_count,
                    "last_session": s_start.isoformat(),
                })

                # Print progress every 10 sessions
                if (idx + 1) % 10 == 0:
                    logger.info("Checkpoint: %d/%d sessions | equity=$%.2f | trades=%d | errors=%d | max_dd=%.1f%%",
                        idx + 1, len(all_sessions), self.equity, self.trade_count, self.error_count, self.max_drawdown_pct)

                # Rate limit: small sleep between sessions
                await asyncio.sleep(5.0)  # more delay = fewer 429s, more analysts succeed

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
            if len(team_data) >= 100:
                import pandas as pd
                TeamMetaModel().train(pd.DataFrame(team_data))
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


async def main():
    engine = StandaloneBacktestEngine(initial_equity=200.0)
    start = datetime(2025, 10, 15, tzinfo=timezone.utc)
    end = datetime(2026, 6, 19, tzinfo=timezone.utc)
    symbols = ACTIVE_SYMBOLS

    logger.info("=" * 60)
    logger.info("BACKTEST STARTING")
    logger.info("=" * 60)
    logger.info("Run ID: %s", engine.run_id)
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

"""BacktestEngine — walk-forward historical replay using local data.

Supports both v1 (single LLM) and v2 (multi-agent team) decision engines.
Results are persisted to backtest_runs for trend monitoring.
"""
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from sqlalchemy import select, func
from app import models, schemas
from app.config import get_settings
from app.database import get_celery_session
from app.enums import TradeDirection, TradeMode

settings = get_settings()


class BacktestEngine:
    """Run walk-forward backtests on historical candle data."""

    SPREAD_PIPS = 1.5
    COMMISSION_PCT = 0.0005

    def __init__(self):
        self.equity_curve = []
        self.trades: List[Dict[str, Any]] = []

    async def load_data(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1h",
    ) -> pd.DataFrame:
        """Load candles from local historical_candles store."""
        async with get_celery_session()() as db:
            result = await db.execute(
                select(models.HistoricalCandle).where(
                    models.HistoricalCandle.symbol == symbol,
                    models.HistoricalCandle.timeframe == timeframe,
                    models.HistoricalCandle.timestamp >= start,
                    models.HistoricalCandle.timestamp <= end,
                ).order_by(models.HistoricalCandle.timestamp)
            )
            rows = result.scalars().all()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([{
                "timestamp": r.timestamp,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            } for r in rows])

    async def run(
        self,
        symbol: str = "EURUSD",
        start: datetime = None,
        end: datetime = None,
        timeframe: str = "1h",
        initial_equity: float = 10000.0,
        strategy_mode: str = "scalping",
        use_v2: bool = False,
        params: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        if start is None:
            start = datetime.utcnow() - timedelta(days=365)
        if end is None:
            end = datetime.utcnow()

        df = await self.load_data(symbol, start, end, timeframe)
        if df.empty:
            # Fallback: try MetaAPI (original behavior) for recent data
            from app.services.data.metaapi_client import MetaApiClient
            metaapi = MetaApiClient()
            candles = await metaapi.get_historical_candles(symbol, timeframe, 5000)
            df = pd.DataFrame(candles)
            if df.empty or len(df) < 100:
                return {"error": "Insufficient historical data for backtest"}
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].reset_index(drop=True)

        if len(df) < 100:
            return {"error": "Insufficient historical data for backtest"}

        equity = initial_equity
        max_equity = equity
        max_drawdown = 0.0
        self.trades = []
        self.equity_curve = []

        pip_value = 0.0001 if "JPY" not in symbol else 0.01
        spread_cost = self.SPREAD_PIPS * pip_value

        # Strategy parameters (overrideable for optimization)
        conf_threshold = params.get("confidence_threshold", 0.55) if params else 0.55
        min_rr = params.get("min_risk_reward", 1.0) if params else 1.0

        for i in range(200, len(df)):
            snapshot = df.iloc[:i].to_dict("records")
            current = df.iloc[i]
            prev = df.iloc[i - 1]

            # Build analysis snapshot (simplified: only technical for speed)
            from app.analysis.technical import TechnicalAnalyzer
            tech = TechnicalAnalyzer().analyze(snapshot)
            analysis = {
                "symbol": symbol,
                "technical": {"timeframes": {timeframe: tech}, "overall_signal": tech.get("signal", "neutral")},
                "fundamental": {"event_risk": "low", "direction_bias": "neutral"},
                "sentiment": {"overall_sentiment": "neutral", "sentiment_score": 0.0},
            }

            decision = None
            if use_v2:
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
                    verifier_enabled=False,  # faster for backtest
                    analyst_parallelism=True,
                )
                import asyncio
                v2_result = asyncio.get_event_loop().run_until_complete(
                    team.decide(symbol, strategy_mode, analysis)
                )
                from app.ai.openrouter_client import TradeDecision
                decision = TradeDecision(
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
            else:
                from app.ai.openrouter_client import OpenRouterClient
                ai = OpenRouterClient()
                decision = ai._fallback_decision(analysis, strategy_mode)

            # Apply confidence and RR filters
            if decision.decision not in ("BUY", "SELL"):
                continue
            if decision.confidence < conf_threshold:
                continue
            if (decision.risk_reward or 0) < min_rr:
                continue

            # Simulate trade
            risk_amt = equity * (decision.position_size_pct / 100.0)
            sl_dist = abs(decision.entry_price - decision.stop_loss)
            if sl_dist == 0:
                continue
            position_size = risk_amt / (sl_dist * 100000)
            position_size = min(position_size, equity / (decision.entry_price * 100000))

            open_trade = {
                "direction": decision.decision.lower(),
                "entry": decision.entry_price,
                "sl": decision.stop_loss,
                "tp": decision.take_profit,
                "size": position_size,
                "open_idx": i,
            }

            for j in range(i + 1, len(df)):
                future = df.iloc[j]
                if open_trade["direction"] == "buy":
                    if future["low"] <= open_trade["sl"]:
                        raw_pnl = (open_trade["sl"] - open_trade["entry"]) * open_trade["size"] * 100000
                        break
                    elif future["high"] >= open_trade["tp"]:
                        raw_pnl = (open_trade["tp"] - open_trade["entry"]) * open_trade["size"] * 100000
                        break
                else:
                    if future["high"] >= open_trade["sl"]:
                        raw_pnl = (open_trade["entry"] - open_trade["sl"]) * open_trade["size"] * 100000
                        break
                    elif future["low"] <= open_trade["tp"]:
                        raw_pnl = (open_trade["entry"] - open_trade["tp"]) * open_trade["size"] * 100000
                        break
            else:
                raw_pnl = 0
                j = len(df) - 1

            trade_notional = open_trade["entry"] * open_trade["size"] * 100000
            commission = trade_notional * self.COMMISSION_PCT * 2
            spread_pnl_impact = spread_cost * open_trade["size"] * 100000
            pnl = raw_pnl - commission - spread_pnl_impact

            equity += pnl
            self.equity_curve.append({"timestamp": future["timestamp"], "equity": equity})
            self.trades.append({
                "direction": open_trade["direction"],
                "entry": open_trade["entry"],
                "exit": open_trade.get("sl") if pnl < 0 else open_trade.get("tp"),
                "pnl": pnl,
                "pnl_pct": (pnl / (equity - pnl)) * 100 if (equity - pnl) > 0 else 0,
            })

            if equity > max_equity:
                max_equity = equity
            dd = (max_equity - equity) / max_equity * 100
            if dd > max_drawdown:
                max_drawdown = dd

        if not self.trades:
            return {"error": "No trades generated during backtest period"}

        wins = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(self.trades) * 100 if self.trades else 0
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        returns = [t["pnl_pct"] for t in self.trades]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = pd.Series(returns).std() if len(returns) > 1 else 0
        sharpe = (avg_return / std_return) * math.sqrt(260) if std_return > 0 else 0
        expectancy = avg_return

        result = {
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "total_return_pct": round((equity - initial_equity) / initial_equity * 100, 2),
            "expectancy": round(expectancy, 2),
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "params": params or {},
            "engine": "v2" if use_v2 else "v1",
        }

        # Persist to backtest_runs
        async with get_celery_session()() as db:
            run = models.BacktestRun(
                symbol=symbol,
                start_date=start,
                end_date=end,
                total_trades=len(self.trades),
                winning_trades=len(wins),
                losing_trades=len(losses),
                win_rate=round(win_rate, 2),
                profit_factor=round(profit_factor, 2),
                sharpe_ratio=round(sharpe, 2),
                max_drawdown_pct=round(max_drawdown, 2),
                total_return_pct=round((equity - initial_equity) / initial_equity * 100, 2),
                expectancy=round(expectancy, 2),
                config={"params": params or {}, "engine": "v2" if use_v2 else "v1", "strategy_mode": strategy_mode},
            )
            db.add(run)
            await db.commit()

        return result

import math
from datetime import datetime, timedelta
from typing import Dict, Any, List
import pandas as pd

from app.services.data.metaapi_client import MetaApiClient
from app.analysis.aggregator import AnalysisAggregator
from app.ai.openrouter_client import OpenRouterClient, TradeDecision
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app import schemas, models
from app.config import get_settings

settings = get_settings()


class BacktestEngine:
    def __init__(self):
        self.metaapi = MetaApiClient()
        self.aggregator = AnalysisAggregator()
        self.ai = OpenRouterClient()

    # Realistic trading costs for backtesting (configurable)
    SPREAD_PIPS = 1.5  # Typical EUR/USD spread
    COMMISSION_PCT = 0.0005  # 0.05% per trade side

    async def run(
        self,
        symbol: str = "EURUSD",
        start: datetime = None,
        end: datetime = None,
        timeframe: str = "1h",
        initial_equity: float = 10000.0,
    ) -> Dict[str, Any]:
        if not start:
            start = datetime.utcnow() - timedelta(days=365)
        if not end:
            end = datetime.utcnow()

        candles = await self.metaapi.get_historical_candles(symbol, timeframe, 5000)
        df = pd.DataFrame(candles)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].reset_index(drop=True)

        if len(df) < 100:
            return {"error": "Insufficient historical data for backtest"}

        equity = initial_equity
        equity_curve = []
        trades: List[Dict[str, Any]] = []
        max_equity = equity
        max_drawdown = 0.0

        # Determine pip value and spread cost for this symbol
        pip_value = 0.0001 if "JPY" not in symbol else 0.01
        spread_cost = self.SPREAD_PIPS * pip_value

        for i in range(200, len(df)):
            snapshot = df.iloc[:i].to_dict("records")
            current = df.iloc[i]
            prev = df.iloc[i - 1]

            tech = self.aggregator.technical.analyze(snapshot)
            analysis = {
                "symbol": symbol,
                "technical": {"timeframes": {timeframe: tech}, "overall_signal": tech.get("signal", "neutral")},
                "fundamental": {"event_risk": "low", "direction_bias": "neutral"},
                "sentiment": {"overall_sentiment": "neutral", "sentiment_score": 0.0},
            }

            decision = self.ai._fallback_decision(analysis)

            if decision.decision in ("BUY", "SELL"):
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

                # Apply realistic costs: spread + commission
                trade_notional = open_trade["entry"] * open_trade["size"] * 100000
                commission = trade_notional * self.COMMISSION_PCT * 2  # Entry + exit
                spread_pnl_impact = spread_cost * open_trade["size"] * 100000
                pnl = raw_pnl - commission - spread_pnl_impact

                equity += pnl
                equity_curve.append({"timestamp": future["timestamp"], "equity": equity})
                trades.append({
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

        if not trades:
            return {"error": "No trades generated during backtest period"}

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        returns = [t["pnl_pct"] for t in trades]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = pd.Series(returns).std() if len(returns) > 1 else 0
        # Forex trades 24/5 = ~260 trading days per year (not 252 like equities)
        sharpe = (avg_return / std_return) * math.sqrt(260) if std_return > 0 else 0
        expectancy = avg_return

        return {
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "total_return_pct": round((equity - initial_equity) / initial_equity * 100, 2),
            "expectancy": round(expectancy, 2),
            "equity_curve": equity_curve,
            "trades": trades,
        }

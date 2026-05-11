from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class TradeDirection(str, Enum):
    buy = "buy"
    sell = "sell"


class TradeMode(str, Enum):
    paper = "paper"
    live = "live"


class TradeCreate(BaseModel):
    symbol: str = "EURUSD"
    direction: TradeDirection
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_pct: Optional[float] = None
    position_size: Optional[float] = None
    mode: TradeMode = TradeMode.paper
    ai_decision_id: Optional[int] = None
    rationale: Optional[str] = None


class TradeOut(BaseModel):
    id: int
    symbol: str
    direction: str
    status: str
    mode: str
    entry_price: Optional[float]
    exit_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: Optional[float]
    risk_pct: Optional[float]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    open_time: Optional[datetime]
    close_time: Optional[datetime]
    created_at: datetime
    rationale: Optional[str]

    class Config:
        from_attributes = True


class AIDecisionOut(BaseModel):
    id: int
    symbol: str
    timestamp: datetime
    decision: str
    confidence: float
    timeframe: Optional[str]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size_pct: Optional[float]
    risk_reward: Optional[float]
    rationale: Optional[str]
    model_used: Optional[str]

    class Config:
        from_attributes = True


class BacktestOut(BaseModel):
    id: int
    symbol: str
    start_date: datetime
    end_date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    sharpe_ratio: Optional[float]
    max_drawdown_pct: Optional[float]
    total_return_pct: Optional[float]
    expectancy: Optional[float]
    config: Optional[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True

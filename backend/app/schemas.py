from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class TradeDirection(str, Enum):
    buy = "buy"
    sell = "sell"


class TradeMode(str, Enum):
    paper = "paper"
    live = "live"


class DataProvider(str, Enum):
    metaapi = "metaapi"
    mt5_zmq = "mt5_zmq"


class TradeCreate(BaseModel):
    symbol: str = "EURUSD"
    direction: TradeDirection
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_pct: Optional[float] = None
    position_size: Optional[float] = None
    mode: TradeMode = TradeMode.paper
    provider: DataProvider = DataProvider.metaapi
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
    provider: Optional[DataProvider] = None

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
    provider: Optional[DataProvider] = None

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


class CandleOut(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketSummaryOut(BaseModel):
    symbol: str
    bid: Optional[float]
    ask: Optional[float]
    spread: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    day_change_pct: Optional[float]
    session_status: str


class PositionOut(BaseModel):
    id: int
    symbol: str
    direction: str
    status: str
    mode: str
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: Optional[float]
    risk_pct: Optional[float]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    open_time: Optional[datetime]
    duration_minutes: Optional[int]
    distance_to_sl: Optional[float]
    distance_to_tp: Optional[float]
    ai_decision_id: Optional[int]
    rationale: Optional[str]

    class Config:
        from_attributes = True


class PortfolioSummaryOut(BaseModel):
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    max_drawdown_pct: Optional[float]
    sharpe_ratio: Optional[float]
    expectancy: Optional[float]


class AnalysisTechnicalOut(BaseModel):
    signal: str
    confidence: float
    indicators: Dict[str, Any]
    support: Optional[float]
    resistance: Optional[float]
    divergence: Optional[str]


class AnalysisFundamentalOut(BaseModel):
    event_risk: str
    high_impact_events: int
    events: List[Dict[str, Any]]
    interest_rate_spread: Optional[float]
    direction_bias: str
    news_headlines: List[str]


class AnalysisSentimentOut(BaseModel):
    overall_sentiment: str
    sentiment_score: float
    retail: Dict[str, Any]
    news: Dict[str, Any]
    institutional: Dict[str, Any]


class AnalysisSummaryOut(BaseModel):
    symbol: str
    technical_signal: str
    fundamental_signal: str
    sentiment_signal: str
    combined_signal: str
    ai_decision: Optional[str]
    ai_confidence: Optional[float]


class ActivePairOut(BaseModel):
    id: int
    symbol: str
    selection_mode: str
    priority: int
    created_at: datetime

    class Config:
        from_attributes = True


class ActivePairCreate(BaseModel):
    symbol: str
    selection_mode: str = "manual"
    priority: int = 1


class AccountInfoOut(BaseModel):
    balance: Optional[float] = None
    equity: Optional[float] = None
    margin: Optional[float] = None
    free_margin: Optional[float] = None
    currency: Optional[str] = None
    leverage: Optional[int] = None


class AppSettingsOut(BaseModel):
    default_pair: str
    max_risk_per_trade_pct: float
    max_risk_per_trade_abs: Optional[float]
    max_daily_loss_pct: float
    ai_confidence_threshold: float
    min_risk_reward: float
    default_mode: str
    manual_override: bool
    max_open_per_symbol: int
    equity_balance: float
    active_pairs: List[Dict[str, Any]]


class AppSettingsUpdate(BaseModel):
    max_risk_per_trade_pct: Optional[float] = None
    max_risk_per_trade_abs: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    ai_confidence_threshold: Optional[float] = None
    min_risk_reward: Optional[float] = None
    default_mode: Optional[str] = None
    manual_override: Optional[bool] = None
    max_open_per_symbol: Optional[int] = None
    equity_balance: Optional[float] = None


class ManualTradeCreate(BaseModel):
    symbol: str
    direction: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_pct: Optional[float] = None
    position_size: Optional[float] = None
    mode: Optional[str] = "paper"
    provider: Optional[DataProvider] = DataProvider.metaapi
    rationale: Optional[str] = None

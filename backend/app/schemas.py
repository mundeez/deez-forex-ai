from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.enums import TradeDirection, TradeMode, DataProvider


class TradeCreate(BaseModel):
    symbol: str = Field(default="EURUSD", min_length=3, max_length=10)
    direction: TradeDirection
    entry_price: Optional[float] = Field(None, ge=0.0)
    stop_loss: Optional[float] = Field(None, ge=0.0)
    take_profit: Optional[float] = Field(None, ge=0.0)
    risk_pct: Optional[float] = Field(None, ge=0.0, le=100.0)
    position_size: Optional[float] = Field(None, ge=0.0)
    mode: TradeMode = TradeMode.PAPER
    provider: DataProvider = DataProvider.METAAPI
    ai_decision_id: Optional[int] = None
    rationale: Optional[str] = None

    @field_validator("symbol")
    @classmethod
    def _uppercase_symbol(cls, v: str) -> str:
        return v.upper()

    @field_validator("stop_loss", "take_profit")
    @classmethod
    def _price_precision(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return round(v, 5)
        return v


class TradeOut(BaseModel):
    id: int
    symbol: str
    direction: str
    status: str
    mode: str
    strategy_mode: Optional[str] = None
    entry_price: Optional[float]
    exit_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: Optional[float]
    original_position_size: Optional[float] = None
    risk_pct: Optional[float]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    partial_pnl: Optional[float] = 0.0
    closed_portion: Optional[float] = 0.0
    open_time: Optional[datetime]
    close_time: Optional[datetime]
    created_at: datetime
    rationale: Optional[str]
    provider: Optional[DataProvider] = None
    trailing_stop_active: Optional[bool] = False
    trailing_stop_distance: Optional[float] = None
    highest_price_seen: Optional[float] = None
    lowest_price_seen: Optional[float] = None

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
    strategy_mode: Optional[str] = None
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    position_size: Optional[float]
    original_position_size: Optional[float] = None
    risk_pct: Optional[float]
    pnl: Optional[float]
    pnl_pct: Optional[float]
    partial_pnl: Optional[float] = 0.0
    closed_portion: Optional[float] = 0.0
    open_time: Optional[datetime]
    duration_minutes: Optional[int]
    distance_to_sl: Optional[float]
    distance_to_tp: Optional[float]
    ai_decision_id: Optional[int]
    rationale: Optional[str]
    trailing_stop_active: Optional[bool] = False
    trailing_stop_distance: Optional[float] = None

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
    data_provider: str
    strategy_mode: str
    max_risk_per_trade_pct: float
    max_risk_per_trade_abs: Optional[float]
    max_daily_loss_pct: float
    ai_confidence_threshold: float
    min_risk_reward: float
    default_mode: str
    manual_override: bool
    max_open_per_symbol: int
    equity_balance: float
    max_trade_duration_min: int
    eod_close_enabled: bool
    eod_close_time_utc: str
    eod_no_new_entries_before: str
    weekend_close_enabled: bool
    weekend_close_time_utc: str
    weekend_resume_time_utc: str
    enable_technical: bool
    enable_fundamental: bool
    enable_sentiment: bool
    chart_refresh_ms: int
    analysis_poll_ms: int
    active_pairs: List[Dict[str, Any]]


class AppSettingsUpdate(BaseModel):
    strategy_mode: Optional[str] = None
    max_risk_per_trade_pct: Optional[float] = Field(None, ge=0.1, le=50.0)
    max_risk_per_trade_abs: Optional[float] = Field(None, ge=0.0)
    max_daily_loss_pct: Optional[float] = Field(None, ge=0.1, le=100.0)
    ai_confidence_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    min_risk_reward: Optional[float] = Field(None, ge=0.1)
    default_mode: Optional[str] = None
    manual_override: Optional[bool] = None
    max_open_per_symbol: Optional[int] = Field(None, ge=1, le=20)
    equity_balance: Optional[float] = Field(None, ge=0.0)
    max_trade_duration_min: Optional[int] = Field(None, ge=1, le=1440)
    eod_close_enabled: Optional[bool] = None
    eod_close_time_utc: Optional[str] = None
    eod_no_new_entries_before: Optional[str] = None
    weekend_close_enabled: Optional[bool] = None
    weekend_close_time_utc: Optional[str] = None
    weekend_resume_time_utc: Optional[str] = None
    enable_technical: Optional[bool] = None
    enable_fundamental: Optional[bool] = None
    enable_sentiment: Optional[bool] = None
    chart_refresh_ms: Optional[int] = Field(None, ge=100, le=60000)
    analysis_poll_ms: Optional[int] = Field(None, ge=1000, le=300000)


class ManualTradeCreate(BaseModel):
    symbol: str
    direction: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_pct: Optional[float] = None
    position_size: Optional[float] = None
    mode: Optional[str] = "paper"
    provider: Optional[DataProvider] = DataProvider.METAAPI
    rationale: Optional[str] = None

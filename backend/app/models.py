from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum


class TradeStatus(str, enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TradeDirection(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class TradeMode(str, enum.Enum):
    PAPER = "paper"
    LIVE = "live"


class DataProvider(str, enum.Enum):
    METAAPI = "metaapi"
    MT5_ZMQ = "mt5_zmq"


class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, default="EURUSD")
    direction = Column(Enum(TradeDirection), nullable=False)
    status = Column(Enum(TradeStatus), default=TradeStatus.PENDING)
    mode = Column(Enum(TradeMode), default=TradeMode.PAPER)
    strategy_mode = Column(String(20), default="scalping")
    entry_price = Column(Float)
    exit_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    position_size = Column(Float)
    risk_pct = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    ai_decision_id = Column(Integer)
    open_time = Column(DateTime(timezone=True))
    close_time = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    meta_order_id = Column(String(100))
    rationale = Column(Text)
    provider = Column(Enum(DataProvider), default=DataProvider.MT5_ZMQ)


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, default="EURUSD")
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    decision = Column(String(10), nullable=False)
    confidence = Column(Float)
    timeframe = Column(String(10))
    entry_price = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    position_size_pct = Column(Float)
    risk_reward = Column(Float)
    rationale = Column(Text)
    technical_snapshot = Column(JSON)
    fundamental_snapshot = Column(JSON)
    sentiment_snapshot = Column(JSON)
    model_used = Column(String(100))
    provider = Column(Enum(DataProvider), default=DataProvider.METAAPI)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, default="EURUSD")
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float)
    profit_factor = Column(Float)
    sharpe_ratio = Column(Float)
    max_drawdown_pct = Column(Float)
    total_return_pct = Column(Float)
    expectancy = Column(Float)
    config = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DailyPnl(Base):
    __tablename__ = "daily_pnl"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime(timezone=True), nullable=False, index=True)
    symbol = Column(String(10), nullable=False)
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    equity = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SettingsTable(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    equity = Column(Float, nullable=False)
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    open_trades = Column(Integer, default=0)


class ActivePair(Base):
    __tablename__ = "active_pairs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False)
    selection_mode = Column(String(10), default="manual")
    priority = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MarketStateSnapshot(Base):
    __tablename__ = "market_state_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    strategy_mode = Column(String(20), default="scalping")
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    technical_vector = Column(JSON)
    decision = Column(String(10))
    confidence = Column(Float)
    outcome_pnl = Column(Float)
    outcome_status = Column(String(20))
    qdrant_point_id = Column(String(50))


class PairPerformanceByHour(Base):
    __tablename__ = "pair_performance_by_hour"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    hour_utc = Column(Integer, nullable=False)
    strategy_mode = Column(String(20), default="scalping")
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    avg_pnl = Column(Float, default=0.0)
    avg_confidence = Column(Float, default=0.0)
    volatility_score = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

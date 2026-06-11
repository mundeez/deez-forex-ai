from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON, Enum
from sqlalchemy.sql import func
from app.database import Base
from app.enums import TradeStatus, TradeDirection, TradeMode, DataProvider


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
    original_position_size = Column(Float)
    risk_pct = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    partial_pnl = Column(Float, default=0.0)
    closed_portion = Column(Float, default=0.0)
    ai_decision_id = Column(Integer)
    open_time = Column(DateTime(timezone=True))
    close_time = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    meta_order_id = Column(String(100))
    rationale = Column(Text)
    provider = Column(Enum(DataProvider), default=DataProvider.MT5_ZMQ)
    trailing_stop_active = Column(Boolean, default=False)
    trailing_stop_distance = Column(Float)
    highest_price_seen = Column(Float)
    lowest_price_seen = Column(Float)
    # Phase 3 columns previously in DB but missing from ORM (close_reason was the
    # source of the never-populated close_reason column bug). Added in v0.9.0.
    close_reason = Column(String(30))
    partial_tp_hit = Column(Boolean, default=False)
    partial_profit_pnl = Column(Float)
    max_risk_amount = Column(Float)
    # v0.9.0 — exit-timing learning foundation
    mfe_pips = Column(Float)
    mae_pips = Column(Float)
    peak_pnl = Column(Float)
    peak_pnl_time = Column(DateTime(timezone=True))
    session_at_open = Column(String(20))
    session_at_close = Column(String(20))
    actual_holding_min = Column(Float)


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
    # v2 AI Team fields
    engine_version = Column(String(10), default="v1")
    analyst_opinions = Column(JSON)
    lead_model = Column(String(100))
    verifier_model = Column(String(100))
    verifier_verdict = Column(String(10))
    regime = Column(JSON)
    daily_bias = Column(JSON)


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
    peak_equity = Column(Float, nullable=False)
    drawdown_pct = Column(Float, default=0.0)
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


class TradeDecisionEvent(Base):
    __tablename__ = "trade_decision_events"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    kind = Column(String(20), nullable=False)  # ENTRY, CHECK, CLOSE, BIAS
    source = Column(String(20), nullable=False)  # AI, RULE, MANUAL, VERIFIER
    snapshot = Column(JSON)
    action = Column(String(20))
    rationale = Column(Text)
    confidence = Column(Float)
    model_used = Column(String(100))


class ModelPerformance(Base):
    __tablename__ = "model_performance"

    id = Column(Integer, primary_key=True, index=True)
    model = Column(String(100), nullable=False, index=True)
    domain = Column(String(20), nullable=False, index=True)  # technical, fundamental, sentiment, macro, lead, verifier, overall
    window = Column(String(20), default="30d")
    trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    expectancy = Column(Float, default=0.0)
    avg_confidence = Column(Float, default=0.0)
    avg_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DailyBias(Base):
    __tablename__ = "daily_bias"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    date = Column(DateTime(timezone=True), nullable=False)
    bias = Column(String(10), nullable=False)
    confidence = Column(Float, default=0.0)
    rationale = Column(Text)
    key_levels = Column(JSON)
    risk_events = Column(JSON)
    model_used = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HistoricalCandle(Base):
    __tablename__ = "historical_candles"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, default=0)
    source = Column(String(20), default="dukascopy")


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    strategy_mode = Column(String(20), nullable=False, index=True)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    params_grid = Column(JSON)
    best_params = Column(JSON)
    fitness = Column(Float)
    total_backtests = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    broker = Column(String(100), nullable=False)
    login = Column(String(50), nullable=False)
    password = Column(String(100), nullable=False)  # TODO: encrypt in production
    server = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=False)
    is_demo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

"""Single source of truth for all domain enums used across models, schemas, and config."""

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


class StrategyMode(str, enum.Enum):
    SCALPING = "scalping"
    DAY_TRADING = "day_trading"
    SWING = "swing"


class EngineVersion(str, enum.Enum):
    V1 = "v1"
    V2 = "v2"

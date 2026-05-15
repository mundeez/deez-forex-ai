from enum import Enum
from pydantic_settings import BaseSettings
from functools import lru_cache


class DataProvider(str, Enum):
    metaapi = "metaapi"
    mt5_zmq = "mt5_zmq"


class StrategyMode(str, Enum):
    scalping = "scalping"
    day_trading = "day_trading"
    swing = "swing"


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://forex:forex_secret@localhost:5432/deez_forex"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    QDRANT_URL: str = "http://localhost:6333"
    META_API_TOKEN: str = ""
    META_API_ACCOUNT_ID: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "anthropic/claude-sonnet-4.5"
    NEWS_API_KEY: str = ""
    FRED_API_KEY: str = ""
    MAX_RISK_PER_TRADE_PCT: float = 2.0
    MAX_DAILY_LOSS_PCT: float = 5.0
    DEFAULT_PAIR: str = "EURUSD"
    APP_ENV: str = "development"
    DATA_PROVIDER: DataProvider = DataProvider.mt5_zmq
    STRATEGY_MODE: StrategyMode = StrategyMode.scalping
    MT5_ZMQ_HOST: str = "host.docker.internal"
    MT5_ZMQ_REQ_PORT: int = 5555
    MT5_ZMQ_PUB_PORT: int = 5556

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

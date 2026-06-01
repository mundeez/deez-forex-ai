import os
from pydantic_settings import BaseSettings
from functools import lru_cache
from app.enums import DataProvider, StrategyMode, EngineVersion


class Settings(BaseSettings):
    # Database & Cache
    DATABASE_URL: str = ""
    REDIS_URL: str = ""
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    QDRANT_URL: str = ""

    # API Keys
    META_API_TOKEN: str = ""
    META_API_ACCOUNT_ID: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-super-120b-a12b:free"
    NEWS_API_KEY: str = ""
    FRED_API_KEY: str = ""

    # Trading Configuration
    MAX_RISK_PER_TRADE_PCT: float = 2.0
    MAX_DAILY_LOSS_PCT: float = 5.0
    DEFAULT_PAIR: str = "EURUSD"
    DATA_PROVIDER: DataProvider = DataProvider.METAAPI
    STRATEGY_MODE: StrategyMode = StrategyMode.SCALPING
    DECISION_ENGINE_VERSION: EngineVersion = EngineVersion.V1

    # v2 AI Team Settings (env-level defaults)
    MODEL_SUITE: str = "free"  # free | production | extreme | custom
    MODEL_TECHNICAL: str = "openai/gpt-oss-120b:free"
    MODEL_FUNDAMENTAL: str = "meta-llama/llama-3.3-70b-instruct:free"
    MODEL_SENTIMENT: str = "qwen/qwen3-next-80b-a3b-instruct:free"
    MODEL_MACRO: str = "deepseek/deepseek-r1:free"
    MODEL_LEAD: str = "openai/gpt-oss-120b:free"
    MODEL_VERIFIER: str = "deepseek/deepseek-r1:free"

    # v2 Feature Flags (env-level defaults)
    VERIFIER_ENABLED: bool = True
    VERIFIER_CAN_VETO: bool = True
    DAILY_BIAS_ENABLED: bool = True
    EXIT_REEVAL_ENABLED: bool = False  # alert-only until validated
    MODEL_PERF_WEIGHTING_ENABLED: bool = False

    # MT5 ZeroMQ Bridge
    MT5_ZMQ_HOST: str = "host.docker.internal"
    MT5_ZMQ_REQ_PORT: int = 5555
    MT5_ZMQ_PUB_PORT: int = 5556

    # Security
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Application
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def validate_settings() -> None:
    """
    Validate that all required environment variables are set.
    Raises ValueError on missing critical settings before app starts.
    """
    s = get_settings()
    required = {
        "DATABASE_URL": s.DATABASE_URL,
        "REDIS_URL": s.REDIS_URL,
        "CELERY_BROKER_URL": s.CELERY_BROKER_URL,
        "CELERY_RESULT_BACKEND": s.CELERY_RESULT_BACKEND,
        "QDRANT_URL": s.QDRANT_URL,
    }
    missing = [k for k, v in required.items() if not v or v.strip() == ""]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Please set them in your .env file. See backend/.env.example for documentation."
        )

    # Warn if OpenRouter key is missing (not fatal, but AI decisions won't work)
    if not s.OPENROUTER_API_KEY or s.OPENROUTER_API_KEY.strip() == "":
        import logging
        logging.getLogger(__name__).warning(
            "OPENROUTER_API_KEY is not set. AI trade decisions will be disabled."
        )

    # Validate origins
    origins = [o.strip() for o in s.ALLOWED_ORIGINS.split(",") if o.strip()]
    if "*" in origins:
        import logging
        logging.getLogger(__name__).warning(
            "ALLOWED_ORIGINS contains '*'. This allows all origins and is insecure for production."
        )

"""Pytest fixtures for the deez-forex-ai test suite."""

import os

# Set required env vars before any app imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

import asyncio
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.enums import TradeDirection, TradeMode, DataProvider, TradeStatus
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.ai.openrouter_client import OpenRouterClient
from app.analysis.aggregator import AnalysisAggregator
from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
import redis.asyncio as aioredis

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DATABASE_URL, future=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def init_app_state():
    """Initialize FastAPI app state (services, redis) once per test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app.state.redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    app.state.metaapi = MetaApiClient()
    app.state.mt5_zmq = MT5ZMQClient()
    app.state.executor = ExecutionService()
    app.state.risk = RiskManager()
    app.state.ai = OpenRouterClient()
    app.state.aggregator = AnalysisAggregator()
    app.state.mt5_sub = None
    yield
    try:
        await app.state.redis.close()
    except Exception:
        pass
    try:
        await app.state.mt5_zmq.close()
    except Exception:
        pass


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create all tables once per session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provide a fresh async DB session for each test."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
def override_get_db(db_session):
    """Override FastAPI dependency to use test DB session."""
    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def async_client(override_get_db):
    """Async HTTP client for testing FastAPI endpoints."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_trade_create():
    """Return a valid TradeCreate payload."""
    from app.schemas import TradeCreate
    return TradeCreate(
        symbol="EURUSD",
        direction=TradeDirection.BUY,
        entry_price=1.0850,
        stop_loss=1.0800,
        take_profit=1.0900,
        risk_pct=1.5,
        mode=TradeMode.PAPER,
        provider=DataProvider.METAAPI,
    )

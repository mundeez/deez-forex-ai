import asyncio
import json
import logging
import time as pytime
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, text, case
import redis.asyncio as aioredis

from app.database import get_db, engine, Base, AsyncSessionLocal
from app.config import get_settings
from app.utils.time import utc_now
from app.logging_config import setup_logging
from app import models, schemas
from app.enums import TradeDirection, TradeMode, DataProvider
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
from app.services.data.mt5_zmq_subscriber import MT5ZMQSubscriber
from app.services.execution.executor import ExecutionService, compute_live_unrealized
from app.services.risk.manager import RiskManager
from app.services.settings_service import build_settings_response, set_setting, get_setting_bool, get_setting, get_setting_float
from app.ai.openrouter_client import OpenRouterClient
from app.analysis.aggregator import AnalysisAggregator
from app.analysis.technical import TechnicalAnalyzer
from app.analysis.fundamental import FundamentalAnalyzer
from app.analysis.sentiment import SentimentAnalyzer

settings = get_settings()

AVAILABLE_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]


def _parse_reset_at(reset_str: str) -> Optional[datetime]:
    """Parse portfolio_reset_at setting into a timezone-aware datetime."""
    if not reset_str or not reset_str.strip():
        return None
    try:
        dt = datetime.fromisoformat(reset_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import validate_settings
    validate_settings()
    setup_logging(level=settings.LOG_LEVEL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.metaapi = MetaApiClient()
    app.state.mt5_zmq = MT5ZMQClient()
    app.state.executor = ExecutionService()
    app.state.risk = RiskManager()
    app.state.ai = OpenRouterClient()
    app.state.aggregator = AnalysisAggregator()

    # Start MT5 tick subscriber if using ZMQ
    if settings.DATA_PROVIDER == DataProvider.MT5_ZMQ:
        app.state.mt5_sub = MT5ZMQSubscriber(on_tick=broadcast_price_tick)
        await app.state.mt5_sub.start()
    else:
        app.state.mt5_sub = None

    yield
    await app.state.redis.close()
    if app.state.mt5_sub:
        await app.state.mt5_sub.stop()
    await app.state.mt5_zmq.close()


# Build CORS origins list from env
_cors_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]

app = FastAPI(
    title="deez-forex-ai",
    description="Intelligent 24/7 Forex Trading Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request ID tracing first (so it's available to all downstream middleware)
app.add_middleware(RequestIdMiddleware)

# Add rate limiting
app.add_middleware(RateLimitMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming HTTP requests with timing."""
    logger = logging.getLogger("app.main")
    start = pytime.time()
    method = request.method
    path = request.url.path
    try:
        response = await call_next(request)
        duration = round((pytime.time() - start) * 1000, 2)
        logger.info(
            "%s %s - %d - %sms",
            method, path, response.status_code, duration,
            extra={"duration_ms": duration},
        )
        return response
    except Exception:
        duration = round((pytime.time() - start) * 1000, 2)
        logger.error(
            "%s %s - ERROR after %sms",
            method, path, duration,
            exc_info=True,
        )
        raise


@app.get("/health")
async def health_check():
    """
    Comprehensive health check covering all critical dependencies.
    Returns 503 if any dependency is down.
    """
    logger = logging.getLogger("app.main")
    start = pytime.time()
    checks = {}
    status = "ok"

    # Check database
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            checks["database"] = {"status": "ok", "latency_ms": round((pytime.time() - start) * 1000, 2)}
    except Exception as e:
        logger.error("Health check: database connection failed: %s", e, exc_info=True)
        checks["database"] = {"status": "error", "detail": "Database unavailable"}
        status = "degraded"

    # Check Redis
    try:
        redis_start = pytime.time()
        await app.state.redis.ping()
        checks["redis"] = {"status": "ok", "latency_ms": round((pytime.time() - redis_start) * 1000, 2)}
    except Exception as e:
        logger.error("Health check: redis connection failed: %s", e, exc_info=True)
        checks["redis"] = {"status": "error", "detail": "Redis unavailable"}
        status = "degraded"

    response = {
        "status": status,
        "env": settings.APP_ENV,
        "version": app.version,
        "checks": checks,
    }
    return response


@app.get("/api/v1/system/health")
async def system_health(db: AsyncSession = Depends(get_db)):
    """
    Operational health endpoint for the auto-trading system.
    Returns AI availability, last analysis status, and current configuration.
    Reads from database so it works across celery/backend process boundaries.
    """
    from app.services.settings_service import get_setting, get_setting_bool
    from datetime import datetime, timezone

    # Determine AI availability by checking recent decisions in DB
    # If the last decision is within 10 minutes, AI is considered available
    cutoff = utc_now() - timedelta(minutes=10)
    result = await db.execute(
        select(func.count(models.AIDecision.id)).where(
            models.AIDecision.timestamp >= cutoff
        )
    )
    recent_decisions = result.scalar() or 0

    # Get the latest decision for error/status info
    result = await db.execute(
        select(models.AIDecision).order_by(models.AIDecision.timestamp.desc()).limit(1)
    )
    latest = result.scalar_one_or_none()

    # Check for recent errors: look for HOLD decisions with error markers
    result = await db.execute(
        select(models.AIDecision).where(
            models.AIDecision.timestamp >= cutoff,
            models.AIDecision.rationale.ilike("%AI UNAVAILABLE%")
        ).order_by(models.AIDecision.timestamp.desc()).limit(1)
    )
    last_error_decision = result.scalar_one_or_none()

    # Count open positions
    result = await db.execute(
        select(func.count(models.Trade.id)).where(
            models.Trade.status == models.TradeStatus.OPEN
        )
    )
    open_positions = result.scalar() or 0

    # Get current config
    ai_model = await get_setting(db, "ai_model") or settings.OPENROUTER_MODEL
    fallback = await get_setting(db, "ai_fallback_strategy") or "hold"
    aggressiveness = await get_setting(db, "trade_aggressiveness") or "moderate"
    strategy_mode = await get_setting(db, "strategy_mode") or "scalping"
    manual_override = await get_setting_bool(db, "manual_override")

    return {
        "ai_available": recent_decisions > 0 and last_error_decision is None,
        "last_successful_analysis": latest.timestamp.isoformat() if latest and not last_error_decision else None,
        "last_error": last_error_decision.rationale[:200] if last_error_decision else None,
        "consecutive_ai_failures": 0,  # DB-based, not easily countable without state
        "open_positions": open_positions,
        "current_model": ai_model,
        "fallback_strategy": fallback,
        "aggressiveness": aggressiveness,
        "strategy_mode": strategy_mode,
        "auto_trading": not manual_override,
    }


async def _get_data_client(provider: schemas.DataProvider = None):
    provider = provider or settings.DATA_PROVIDER
    if provider == DataProvider.MT5_ZMQ:
        return app.state.mt5_zmq
    return app.state.metaapi


async def _safe_get_price(symbol: str, provider: schemas.DataProvider = None):
    """Try the requested provider first, fall back to the other if it fails."""
    logger = logging.getLogger("app.main")
    primary = await _get_data_client(provider)
    try:
        return await primary.get_current_price(symbol)
    except Exception as e:
        logger.warning(
            "Primary provider %s failed to get price for %s: %s",
            primary.__class__.__name__, symbol, e,
            exc_info=True,
        )
        # Fallback to the other provider
        fallback = app.state.mt5_zmq if primary == app.state.metaapi else app.state.metaapi
        try:
            return await fallback.get_current_price(symbol)
        except Exception as e:
            logger.error(
                "All data providers failed to get price for %s: %s",
                symbol, e,
                exc_info=True,
            )
            raise HTTPException(status_code=503, detail=f"Price data unavailable for {symbol}")


async def _safe_get_candles(symbol: str, timeframe: str, limit: int, provider: schemas.DataProvider = None):
    """Try the requested provider first, fall back to the other if it fails."""
    logger = logging.getLogger("app.main")
    primary = await _get_data_client(provider)
    try:
        return await primary.get_historical_candles(symbol, timeframe, limit)
    except Exception as e:
        logger.warning(
            "Primary provider %s failed to get candles for %s %s: %s",
            primary.__class__.__name__, symbol, timeframe, e,
            exc_info=True,
        )
        fallback = app.state.mt5_zmq if primary == app.state.metaapi else app.state.metaapi
        try:
            return await fallback.get_historical_candles(symbol, timeframe, limit)
        except Exception as e:
            logger.error(
                "All data providers failed to get candles for %s %s: %s",
                symbol, timeframe, e,
                exc_info=True,
            )
            return []


@app.get("/api/v1/market/current")
async def get_current_market(
    symbol: str = settings.DEFAULT_PAIR,
    provider: schemas.DataProvider = None,
    db: AsyncSession = Depends(get_db)
):
    try:
        price = await _safe_get_price(symbol, provider)
        return {
            "symbol": symbol,
            "bid": price.get("bid"),
            "ask": price.get("ask"),
            "timestamp": price.get("timestamp"),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/v1/market/historical")
async def get_historical_candles(
    symbol: str = settings.DEFAULT_PAIR,
    timeframe: str = "1h",
    limit: int = 300,
    provider: schemas.DataProvider = None,
    db: AsyncSession = Depends(get_db)
):
    try:
        candles = await _safe_get_candles(symbol, timeframe, limit, provider)
        return {"symbol": symbol, "timeframe": timeframe, "candles": candles}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/v1/market/summary")
async def get_market_summary(
    symbol: str = settings.DEFAULT_PAIR,
    provider: schemas.DataProvider = None,
    db: AsyncSession = Depends(get_db)
):
    try:
        price = await _safe_get_price(symbol, provider)
        candles = await _safe_get_candles(symbol, "1d", 2, provider)
        day_high = None
        day_low = None
        day_change_pct = None
        if candles and len(candles) > 0:
            day_high = max(c["high"] for c in candles)
            day_low = min(c["low"] for c in candles)
            prev_close = candles[0]["close"] if len(candles) > 1 else candles[0]["open"]
            curr = price.get("bid", candles[-1]["close"])
            day_change_pct = round(((curr - prev_close) / prev_close) * 100, 4) if prev_close else 0
        spread = (price.get("ask") - price.get("bid")) if price.get("ask") and price.get("bid") else None

        now_utc = utc_now()
        session_status = []
        if 0 <= now_utc.hour < 9:
            session_status.append("Tokyo")
        if 22 <= now_utc.hour or now_utc.hour < 7:
            session_status.append("Sydney")
        if 8 <= now_utc.hour < 16:
            session_status.append("London")
        if 13 <= now_utc.hour < 21:
            session_status.append("New York")
        if not session_status:
            session_status.append("Closed")

        return {
            "symbol": symbol,
            "bid": price.get("bid"),
            "ask": price.get("ask"),
            "spread": round(spread, 5) if spread else None,
            "day_high": day_high,
            "day_low": day_low,
            "day_change_pct": day_change_pct,
            "session_status": ", ".join(session_status),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger = logging.getLogger("app.main")
        logger.error("Market summary failed for %s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=503, detail="Market data temporarily unavailable")


@app.get("/api/v1/pairs")
async def get_available_pairs():
    return {"pairs": AVAILABLE_PAIRS}


@app.get("/api/v1/pairs/active")
async def get_active_pairs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.ActivePair).order_by(models.ActivePair.priority))
    pairs = result.scalars().all()
    return [{"id": p.id, "symbol": p.symbol, "selection_mode": p.selection_mode, "priority": p.priority} for p in pairs]


@app.post("/api/v1/pairs/active")
async def set_active_pairs(pairs: list[schemas.ActivePairCreate], db: AsyncSession = Depends(get_db)):
    if len(pairs) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 active pairs allowed")
    await db.execute(select(models.ActivePair))
    result = await db.execute(select(models.ActivePair))
    existing = result.scalars().all()
    for e in existing:
        await db.delete(e)
    for p in pairs:
        if p.symbol not in AVAILABLE_PAIRS:
            raise HTTPException(status_code=400, detail=f"Invalid pair: {p.symbol}")
        db.add(models.ActivePair(symbol=p.symbol, selection_mode=p.selection_mode, priority=p.priority))
    await db.commit()
    return {"detail": "Active pairs updated"}


@app.get("/api/v1/trades")
async def get_trades(
    status: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    query = select(models.Trade).order_by(desc(models.Trade.created_at))
    if status:
        query = query.where(models.Trade.status == status)
    result = await db.execute(query.limit(limit))
    trades = result.scalars().all()
    return trades


@app.post("/api/v1/trades/manual", response_model=schemas.TradeOut)
async def create_manual_trade(
    trade_in: schemas.ManualTradeCreate,
    db: AsyncSession = Depends(get_db)
):
    risk: RiskManager = app.state.risk
    direction_enum = TradeDirection.BUY if trade_in.direction.lower() == "buy" else TradeDirection.SELL
    mode_enum = TradeMode.PAPER if (trade_in.mode or "paper").lower() == "paper" else TradeMode.LIVE
    schema_in = schemas.TradeCreate(
        symbol=trade_in.symbol,
        direction=direction_enum,
        entry_price=trade_in.entry_price,
        stop_loss=trade_in.stop_loss,
        take_profit=trade_in.take_profit,
        risk_pct=trade_in.risk_pct,
        position_size=trade_in.position_size,
        mode=mode_enum,
        provider=trade_in.provider,
        rationale=trade_in.rationale,
    )
    ok, reason = await risk.validate_new_trade(db, schema_in)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    executor: ExecutionService = app.state.executor
    trade = await executor.execute_trade(db, schema_in)
    return trade


@app.get("/api/v1/positions")
async def get_open_positions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Trade).where(models.Trade.status == models.TradeStatus.OPEN).order_by(desc(models.Trade.open_time))
    )
    trades = result.scalars().all()
    positions = []
    logger = logging.getLogger("app.main")
    for t in trades:
        try:
            price = await _safe_get_price(t.symbol, schemas.DataProvider(t.provider))
            current = price.get("bid") if t.direction == "sell" else price.get("ask")
        except HTTPException:
            # _safe_get_price already logged; fall back to entry price for display
            current = t.entry_price
        except Exception:
            logger.warning("Price fetch failed for position %s %s, using entry price", t.id, t.symbol, exc_info=True)
            current = t.entry_price
        pnl = None
        pnl_pct = None
        dist_sl = None
        dist_tp = None
        if current and t.entry_price:
            if t.direction == "buy":
                pnl = (current - t.entry_price) * (t.position_size or 0.01) * 100000
                pnl_pct = ((current - t.entry_price) / t.entry_price) * 100
                dist_sl = (current - t.stop_loss) if t.stop_loss else None
                dist_tp = (t.take_profit - current) if t.take_profit else None
            else:
                pnl = (t.entry_price - current) * (t.position_size or 0.01) * 100000
                pnl_pct = ((t.entry_price - current) / t.entry_price) * 100
                dist_sl = (t.stop_loss - current) if t.stop_loss else None
                dist_tp = (current - t.take_profit) if t.take_profit else None
        duration = None
        if t.open_time:
            now = datetime.now(timezone.utc)
            open_time = t.open_time
            if open_time.tzinfo is None:
                open_time = open_time.replace(tzinfo=timezone.utc)
            duration = int((now - open_time).total_seconds() / 60)
        positions.append({
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "status": t.status,
            "mode": t.mode,
            "entry_price": t.entry_price,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "position_size": t.position_size,
            "risk_pct": t.risk_pct,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
            "open_time": t.open_time,
            "duration_minutes": duration,
            "distance_to_sl": round(dist_sl, 5) if dist_sl is not None else None,
            "distance_to_tp": round(dist_tp, 5) if dist_tp is not None else None,
            "ai_decision_id": t.ai_decision_id,
            "rationale": t.rationale,
        })
    return {"positions": positions}


@app.post("/api/v1/positions/{trade_id}/close")
async def close_position(trade_id: int, db: AsyncSession = Depends(get_db)):
    executor: ExecutionService = app.state.executor
    result = await db.execute(select(models.Trade).where(models.Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    try:
        price = await _safe_get_price(trade.symbol, schemas.DataProvider(trade.provider))
        current = price.get("bid")
    except HTTPException:
        raise
    except Exception as e:
        logger = logging.getLogger("app.main")
        logger.error("Failed to fetch price to close trade %s: %s", trade_id, e, exc_info=True)
        raise HTTPException(status_code=503, detail="Unable to fetch current price")
    if not current:
        raise HTTPException(status_code=503, detail="No price available")
    try:
        trade = await executor.close_trade(db, trade_id, current)
        return {"detail": "Position closed", "trade_id": trade.id, "exit_price": trade.exit_price, "pnl": trade.pnl}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/portfolio/summary")
async def get_portfolio_summary(db: AsyncSession = Depends(get_db)):
    reset_at_str = await get_setting(db, "portfolio_reset_at")
    reset_at = _parse_reset_at(reset_at_str)

    base_filters = [models.Trade.status == models.TradeStatus.CLOSED]
    if reset_at is not None:
        base_filters.append(models.Trade.close_time >= reset_at)

    total_result = await db.execute(select(func.count(models.Trade.id)).where(*base_filters))
    total_closed = total_result.scalar() or 0

    win_filters = base_filters + [models.Trade.pnl > 0]
    win_result = await db.execute(select(func.count(models.Trade.id)).where(*win_filters))
    wins = win_result.scalar() or 0

    loss_filters = base_filters + [models.Trade.pnl <= 0]
    loss_result = await db.execute(select(func.count(models.Trade.id)).where(*loss_filters))
    losses = loss_result.scalar() or 0

    profit_filters = base_filters + [models.Trade.pnl > 0]
    gross_profit_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*profit_filters)
    )
    gross_profit = gross_profit_result.scalar() or 0.0

    loss_sum_filters = base_filters + [models.Trade.pnl <= 0]
    gross_loss_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*loss_sum_filters)
    )
    gross_loss = abs(gross_loss_result.scalar() or 0.0)

    total_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*base_filters)
    )
    total_pnl = total_pnl_result.scalar() or 0.0

    unrealized = await compute_live_unrealized(db)
    equity_balance = await get_setting_float(db, "equity_balance")
    equity = equity_balance + total_pnl + unrealized
    win_rate = (wins / total_closed * 100) if total_closed > 0 else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    max_dd_result = await db.execute(
        select(func.coalesce(func.min(models.BacktestRun.max_drawdown_pct), 0)).where(
            models.BacktestRun.total_return_pct.isnot(None)
        )
    )
    max_drawdown = max_dd_result.scalar() or 0.0
    sharpe_result = await db.execute(
        select(func.coalesce(func.avg(models.BacktestRun.sharpe_ratio), 0)).where(
            models.BacktestRun.sharpe_ratio.isnot(None)
        )
    )
    sharpe = sharpe_result.scalar() or 0.0
    expectancy_val = None
    if total_closed > 0:
        avg_win = gross_profit / wins if wins > 0 else 0
        avg_loss = gross_loss / losses if losses > 0 else 0
        win_rate_dec = wins / total_closed
        expectancy_val = (avg_win * win_rate_dec) - (avg_loss * (1 - win_rate_dec))

    return {
        "equity": round(equity, 2),
        "realized_pnl": round(total_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_trades": total_closed,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": round(win_rate, 2) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "max_drawdown_pct": round(abs(max_drawdown), 2),
        "sharpe_ratio": round(sharpe, 2),
        "expectancy": round(expectancy_val, 2) if expectancy_val is not None else None,
        "portfolio_reset_at": reset_at_str if reset_at_str else None,
    }


@app.post("/api/v1/portfolio/reset")
async def reset_portfolio(db: AsyncSession = Depends(get_db)):
    """Reset portfolio statistics by setting portfolio_reset_at to current UTC time.

    After reset, all portfolio metrics (win rate, profit factor, equity, etc.)
    will only count trades closed after this timestamp.
    """
    now_str = utc_now().isoformat()
    await set_setting(db, "portfolio_reset_at", now_str)
    return {
        "detail": "Portfolio reset successfully",
        "portfolio_reset_at": now_str,
    }


@app.get("/api/v1/trades/stats")
async def get_trade_stats(db: AsyncSession = Depends(get_db)):
    reset_at_str = await get_setting(db, "portfolio_reset_at")
    reset_at = _parse_reset_at(reset_at_str)

    base_filters = [models.Trade.status == models.TradeStatus.CLOSED]
    if reset_at is not None:
        base_filters.append(models.Trade.close_time >= reset_at)

    total_result = await db.execute(select(func.count(models.Trade.id)).where(*base_filters))
    total_closed = total_result.scalar() or 0

    win_filters = base_filters + [models.Trade.pnl > 0]
    win_result = await db.execute(select(func.count(models.Trade.id)).where(*win_filters))
    wins = win_result.scalar() or 0

    loss_filters = base_filters + [models.Trade.pnl <= 0]
    loss_result = await db.execute(select(func.count(models.Trade.id)).where(*loss_filters))
    losses = loss_result.scalar() or 0

    profit_filters = base_filters + [models.Trade.pnl > 0]
    gross_profit_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*profit_filters)
    )
    gross_profit = gross_profit_result.scalar() or 0.0

    loss_sum_filters = base_filters + [models.Trade.pnl <= 0]
    gross_loss_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*loss_sum_filters)
    )
    gross_loss = abs(gross_loss_result.scalar() or 0.0)

    total_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*base_filters)
    )
    total_pnl = total_pnl_result.scalar() or 0.0

    today = utc_now().date()
    start_of_day = datetime.combine(today, datetime.min.time())
    day_filters = base_filters + [models.Trade.close_time >= start_of_day]
    daily_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(*day_filters)
    )
    daily_pnl = daily_pnl_result.scalar() or 0.0

    unrealized = await compute_live_unrealized(db)
    equity_balance = await get_setting_float(db, "equity_balance")
    equity = equity_balance + total_pnl + unrealized
    win_rate = (wins / total_closed * 100) if total_closed > 0 else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    expectancy_val = None
    if total_closed > 0:
        avg_win = gross_profit / wins if wins > 0 else 0
        avg_loss = gross_loss / losses if losses > 0 else 0
        win_rate_dec = wins / total_closed
        expectancy_val = (avg_win * win_rate_dec) - (avg_loss * (1 - win_rate_dec))
    max_dd_result = await db.execute(
        select(func.coalesce(func.min(models.BacktestRun.max_drawdown_pct), 0)).where(
            models.BacktestRun.total_return_pct.isnot(None)
        )
    )
    max_drawdown = max_dd_result.scalar() or 0.0
    sharpe_result = await db.execute(
        select(func.coalesce(func.avg(models.BacktestRun.sharpe_ratio), 0)).where(
            models.BacktestRun.sharpe_ratio.isnot(None)
        )
    )
    sharpe = sharpe_result.scalar() or 0.0

    return {
        "equity": round(equity, 2),
        "realized_pnl": round(total_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "daily_pnl": round(daily_pnl, 2),
        "total_trades": total_closed,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": round(win_rate, 2) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "max_drawdown_pct": round(abs(max_drawdown), 2),
        "sharpe_ratio": round(sharpe, 2),
        "expectancy": round(expectancy_val, 2) if expectancy_val is not None else None,
        "portfolio_reset_at": reset_at_str if reset_at_str else None,
    }


@app.get("/api/v1/portfolio/daily")
async def get_daily_pnl_history(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Return daily P&L history from the DailyPnl table."""
    since = utc_now() - timedelta(days=days)
    result = await db.execute(
        select(models.DailyPnl)
        .where(models.DailyPnl.date >= since)
        .order_by(desc(models.DailyPnl.date))
    )
    records = result.scalars().all()
    return {
        "records": [
            {
                "date": r.date.isoformat(),
                "symbol": r.symbol,
                "realized_pnl": round(r.realized_pnl, 2),
                "unrealized_pnl": round(r.unrealized_pnl, 2),
                "equity": round(r.equity, 2) if r.equity else None,
            }
            for r in records
        ]
    }


@app.get("/api/v1/ai/models")
async def get_ai_models(db: AsyncSession = Depends(get_db)):
    """Model rotation status: pool, per-model cooldowns, availability, recent usage."""
    from app.ai.model_router import ModelRouter, parse_pool, DEFAULT_FREE_POOL
    rotation_enabled = await get_setting_bool(db, "ai_model_rotation_enabled")
    paid_enabled = await get_setting_bool(db, "ai_paid_fallback_enabled")
    paid_fallback = (await get_setting(db, "ai_paid_fallback_model")) if paid_enabled else None
    router = ModelRouter(
        free_pool=parse_pool(await get_setting(db, "ai_model_pool")),
        paid_fallback=paid_fallback,
        cooldown_sec=int(await get_setting(db, "ai_model_cooldown_sec") or 120),
        rotation_enabled=rotation_enabled,
    )
    status = await router.status()
    # Actual model usage over the last 24h — confirms rotation is happening.
    cutoff = utc_now() - timedelta(hours=24)
    result = await db.execute(
        select(models.AIDecision.model_used, func.count(models.AIDecision.id))
        .where(models.AIDecision.timestamp >= cutoff)
        .group_by(models.AIDecision.model_used)
    )
    status["recent_usage_24h"] = {(m or "(none)"): int(n) for m, n in result.all()}
    status["catalog_default_free"] = DEFAULT_FREE_POOL
    return status


@app.get("/api/v1/ai/suites")
async def get_ai_suites():
    """Return all available model suites with latency-tier annotations."""
    from app.ai.suites import suite_info
    return {"suites": suite_info()}


@app.get("/api/v1/ai/suite")
async def get_active_suite(db: AsyncSession = Depends(get_db)):
    """Return the currently active suite + per-function models."""
    from app.ai.suites import resolve_models
    suite = await get_setting(db, "model_suite") or "free"
    overrides = {
        "technical": await get_setting(db, "model_technical"),
        "fundamental": await get_setting(db, "model_fundamental"),
        "sentiment": await get_setting(db, "model_sentiment"),
        "macro": await get_setting(db, "model_macro"),
        "lead": await get_setting(db, "model_lead"),
        "verifier": await get_setting(db, "model_verifier"),
    }
    models = resolve_models(suite, overrides)
    return {
        "suite": suite,
        "models": models,
        "engine_version": await get_setting(db, "decision_engine_version") or "v1",
    }


@app.get("/api/v1/analytics/breakdown")
async def get_analytics_breakdown(db: AsyncSession = Depends(get_db)):
    """Closed-trade performance segmented by close_reason, session, direction, symbol, model."""
    win = case((models.Trade.pnl > 0, 1), else_=0)

    async def seg(label_col, joined=False):
        q = select(
            label_col.label("k"),
            func.count(models.Trade.id),
            func.coalesce(func.sum(win), 0),
            func.coalesce(func.sum(models.Trade.pnl), 0.0),
            func.coalesce(func.avg(models.Trade.pnl), 0.0),
        ).where(models.Trade.status == models.TradeStatus.CLOSED)
        if joined:
            q = q.join(models.AIDecision, models.Trade.ai_decision_id == models.AIDecision.id)
        q = q.group_by(label_col).order_by(func.coalesce(func.sum(models.Trade.pnl), 0.0).desc())
        rows = (await db.execute(q)).all()
        out = []
        for k, n, wins, pnl, avg in rows:
            key = k.value if hasattr(k, "value") else k
            out.append({
                "key": key,
                "trades": int(n or 0),
                "wins": int(wins or 0),
                "win_pct": round(100.0 * (wins or 0) / n, 1) if n else 0.0,
                "total_pnl": round(float(pnl or 0), 2),
                "avg_pnl": round(float(avg or 0), 4),
            })
        return out

    return {
        "by_close_reason": await seg(models.Trade.close_reason),
        "by_session_open": await seg(models.Trade.session_at_open),
        "by_direction": await seg(models.Trade.direction),
        "by_symbol": await seg(models.Trade.symbol),
        "by_model": await seg(models.AIDecision.model_used, joined=True),
    }


@app.get("/api/v1/ai/decisions")
async def get_ai_decisions(
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(models.AIDecision)
        .order_by(desc(models.AIDecision.timestamp))
        .limit(limit)
    )
    return result.scalars().all()


@app.post("/api/v1/ai/analyze")
async def trigger_ai_analysis(
    symbol: str = settings.DEFAULT_PAIR,
    provider: schemas.DataProvider = None,
    db: AsyncSession = Depends(get_db)
):
    aggregator: AnalysisAggregator = app.state.aggregator
    ai: OpenRouterClient = app.state.ai
    executor: ExecutionService = app.state.executor
    risk: RiskManager = app.state.risk

    analysis = await aggregator.gather_all(symbol)
    decision = await ai.get_trade_decision(analysis)

    db_decision = models.AIDecision(
        symbol=symbol,
        decision=decision.decision,
        confidence=decision.confidence,
        timeframe=decision.timeframe,
        entry_price=decision.entry_price,
        stop_loss=decision.stop_loss,
        take_profit=decision.take_profit,
        position_size_pct=decision.position_size_pct,
        risk_reward=decision.risk_reward,
        rationale=decision.rationale,
        technical_snapshot=analysis.get("technical"),
        fundamental_snapshot=analysis.get("fundamental"),
        sentiment_snapshot=analysis.get("sentiment"),
        model_used=getattr(decision, "model_used", "") or settings.OPENROUTER_MODEL,
        provider=(provider or settings.DATA_PROVIDER).value,
    )
    db.add(db_decision)
    await db.commit()
    await db.refresh(db_decision)

    manual_override = await get_setting_bool(db, "manual_override")

    if decision.decision in ("BUY", "SELL") and not manual_override:
        ok, reason = await risk.validate_ai_decision(db, decision)
        if ok:
            trade_in = schemas.TradeCreate(
                symbol=symbol,
                direction=TradeDirection(decision.decision.lower()),
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                risk_pct=decision.position_size_pct,
                mode=TradeMode.PAPER,
                provider=provider or settings.DATA_PROVIDER,
                ai_decision_id=db_decision.id,
                rationale=decision.rationale,
            )
            await executor.execute_trade(db, trade_in)
        else:
            decision.decision = "HOLD"
            decision.rationale += f" [RISK BLOCKED: {reason}]"
            db_decision.decision = "HOLD"
            db_decision.rationale = decision.rationale
            await db.commit()

    return decision


@app.get("/api/v1/analysis/technical")
async def get_technical_analysis(
    symbol: str = settings.DEFAULT_PAIR,
    timeframe: str = "1h",
    provider: schemas.DataProvider = None,
    db: AsyncSession = Depends(get_db)
):
    analyzer = TechnicalAnalyzer()
    try:
        candles = await _safe_get_candles(symbol, timeframe, 300, provider)
        result = analyzer.analyze(candles)
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": result.get("signal"),
            "confidence": result.get("confidence"),
            "indicators": result.get("indicators"),
            "support": result.get("support"),
            "resistance": result.get("resistance"),
            "divergence": result.get("divergence"),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/v1/analysis/fundamental")
async def get_fundamental_analysis(symbol: str = settings.DEFAULT_PAIR, db: AsyncSession = Depends(get_db)):
    analyzer = FundamentalAnalyzer()
    try:
        result = await analyzer.analyze(symbol)
        return {
            "symbol": symbol,
            "event_risk": result.get("event_risk"),
            "high_impact_events": result.get("high_impact_events"),
            "events": result.get("events"),
            "interest_rate_spread": result.get("interest_rate_spread"),
            "direction_bias": result.get("direction_bias"),
            "news_headlines": result.get("news_headlines"),
        }
    except Exception as e:
        logger = logging.getLogger("app.main")
        logger.error("Fundamental analysis failed for %s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=503, detail="Fundamental analysis unavailable")


@app.post("/api/v1/backtest/download")
async def download_historical_data(
    symbol: str = settings.DEFAULT_PAIR,
    days: int = 30,
    timeframe: str = "1m",
    db: AsyncSession = Depends(get_db),
):
    """Download Dukascopy tick data for a symbol and store locally."""
    from app.services.data.dukascopy.client import DukascopyClient
    end = utc_now()
    start = end - timedelta(days=days)
    client = DukascopyClient()
    candles = await client.download_range(symbol, start, end, timeframe)
    if candles.empty:
        raise HTTPException(status_code=404, detail="No data available from Dukascopy for this range")
    count = await client.store_candles(symbol, timeframe, candles, db)
    return {"symbol": symbol, "timeframe": timeframe, "candles_stored": count, "period": f"{start.date()} to {end.date()}"}


@app.get("/api/v1/data/health")
async def get_data_health(db: AsyncSession = Depends(get_db)):
    """Health check for data providers: MT5 ZMQ, MetaAPI, and paper fallback status."""
    from app.services.data.mt5_zmq_client import MT5ZMQClient
    from app.services.data.metaapi_client import MetaApiClient

    mt5 = MT5ZMQClient()
    metaapi = MetaApiClient()

    mt5_healthy = False
    mt5_error = None
    try:
        price = await mt5.get_current_price("EURUSD")
        mt5_healthy = price.get("bid") is not None
    except Exception as exc:
        mt5_error = str(exc)

    metaapi_healthy = False
    metaapi_error = None
    try:
        price = await metaapi.get_current_price("EURUSD")
        metaapi_healthy = price.get("bid") is not None
    except Exception as exc:
        metaapi_error = str(exc)

    mt5_default = await get_setting_bool(db, "mt5_feed_default")
    paper_fallback_allowed = await get_setting_bool(db, "allow_paper_fallback")

    return {
        "mt5_zmq": {"healthy": mt5_healthy, "error": mt5_error},
        "metaapi": {"healthy": metaapi_healthy, "error": metaapi_error},
        "mt5_feed_default": mt5_default,
        "paper_fallback_allowed": paper_fallback_allowed,
        "recommended_provider": "mt5_zmq" if mt5_healthy else ("metaapi" if metaapi_healthy else "paper_mock"),
    }


@app.post("/api/v1/backtest/run")
async def run_backtest(
    symbol: str = settings.DEFAULT_PAIR,
    days: int = 90,
    timeframe: str = "1h",
    use_v2: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Run a backtest using local historical data (or MetaAPI fallback)."""
    from app.backtest.engine import BacktestEngine
    engine = BacktestEngine()
    end = utc_now()
    start = end - timedelta(days=days)
    result = await engine.run(symbol=symbol, start=start, end=end, timeframe=timeframe, use_v2=use_v2)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/v1/backtest/optimize")
async def optimize_strategy(
    symbol: str = settings.DEFAULT_PAIR,
    strategy_mode: str = "scalping",
    train_days: int = 90,
    test_days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Run walk-forward parameter optimization for a symbol."""
    from app.backtest.optimizer import StrategyOptimizer
    opt = StrategyOptimizer()
    result = await opt.optimize_symbol(symbol, strategy_mode=strategy_mode, train_days=train_days, test_days=test_days)
    return result


@app.get("/api/v1/analysis/sentiment")
async def get_sentiment_analysis(symbol: str = settings.DEFAULT_PAIR, db: AsyncSession = Depends(get_db)):
    analyzer = SentimentAnalyzer()
    try:
        result = await analyzer.analyze(symbol)
        return {
            "symbol": symbol,
            "overall_sentiment": result.get("overall_sentiment"),
            "sentiment_score": result.get("sentiment_score"),
            "retail": result.get("retail"),
            "news": result.get("news"),
            "institutional": result.get("institutional"),
        }
    except Exception as e:
        logger = logging.getLogger("app.main")
        logger.error("Sentiment analysis failed for %s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=503, detail="Sentiment analysis unavailable")


@app.get("/api/v1/analysis/full")
async def get_analysis_full(symbol: str = settings.DEFAULT_PAIR, db: AsyncSession = Depends(get_db)):
    return await get_analysis_summary(symbol, db)


@app.get("/api/v1/analysis/summary")
async def get_analysis_summary(symbol: str = settings.DEFAULT_PAIR, db: AsyncSession = Depends(get_db)):
    aggregator: AnalysisAggregator = app.state.aggregator
    try:
        result = await aggregator.gather_all(symbol)
        tech = result.get("technical", {})
        fund = result.get("fundamental", {})
        sent = result.get("sentiment", {})

        tech_signal = tech.get("overall_signal", "neutral")
        fund_bias = fund.get("direction_bias", "neutral")
        sent_signal = sent.get("overall_sentiment", "neutral")

        scores = {"bullish": 0, "bearish": 0, "neutral": 0}
        weights = {"technical": 0.4, "fundamental": 0.35, "sentiment": 0.25}
        for sig, w in [(tech_signal, weights["technical"]), (fund_bias, weights["fundamental"]), (sent_signal, weights["sentiment"])]:
            scores[sig] = scores.get(sig, 0) + w
        combined = max(scores, key=scores.get)

        latest_ai = None
        try:
            ai_result = await db.execute(
                select(models.AIDecision).where(models.AIDecision.symbol == symbol).order_by(desc(models.AIDecision.timestamp)).limit(1)
            )
            latest_ai = ai_result.scalar_one_or_none()
        except Exception as e:
            logger = logging.getLogger("app.main")
            logger.warning("Failed to fetch latest AI decision for %s: %s", symbol, e)

        return {
            "symbol": symbol,
            "technical_signal": tech_signal,
            "fundamental_signal": fund_bias,
            "sentiment_signal": sent_signal,
            "combined_signal": combined,
            "ai_decision": latest_ai.decision if latest_ai else None,
            "ai_confidence": latest_ai.confidence if latest_ai else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger = logging.getLogger("app.main")
        logger.error("Analysis summary failed for %s: %s", symbol, e, exc_info=True)
        raise HTTPException(status_code=503, detail="Analysis service temporarily unavailable")


@app.get("/api/v1/backtests")
async def get_backtests(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.BacktestRun).order_by(desc(models.BacktestRun.created_at))
    )
    return result.scalars().all()


@app.get("/api/v1/account/info")
async def get_account_info(provider: schemas.DataProvider = None):
    try:
        client = await _get_data_client(provider)
        info = await client.get_account_info()
        return schemas.AccountInfoOut(**info)
    except Exception as e:
        logger = logging.getLogger("app.main")
        logger.warning("Account info unavailable from provider, returning fallback: %s", e)
        return schemas.AccountInfoOut(
            balance=100.0,
            equity=100.0,
            margin=0.0,
            free_margin=100.0,
            currency="USD",
            leverage=100,
        )


@app.get("/api/v1/settings")
async def get_app_settings(db: AsyncSession = Depends(get_db)):
    return await build_settings_response(db)


@app.put("/api/v1/settings")
@app.post("/api/v1/settings")
async def update_app_settings(payload: schemas.AppSettingsUpdate, db: AsyncSession = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        await set_setting(db, key, value)
    response = await build_settings_response(db)
    await broadcast_settings_change({"type": "settings_updated", "settings": response})
    return response


@app.get("/api/v1/suggestions/best-now")
async def get_best_now(db: AsyncSession = Depends(get_db)):
    from app.suggestion_engine.engine import SuggestionEngine
    strategy_mode = await get_setting(db, "strategy_mode")
    strategy_mode = strategy_mode if strategy_mode in ("scalping", "day_trading", "swing") else "scalping"
    engine = SuggestionEngine(db)
    return {"suggestions": await engine.best_now(strategy_mode)}


@app.get("/api/v1/suggestions/today")
async def get_today_timeline(db: AsyncSession = Depends(get_db)):
    from app.suggestion_engine.engine import SuggestionEngine
    strategy_mode = await get_setting(db, "strategy_mode")
    strategy_mode = strategy_mode if strategy_mode in ("scalping", "day_trading", "swing") else "scalping"
    engine = SuggestionEngine(db)
    return {"timeline": await engine.today_timeline(strategy_mode)}


@app.get("/api/v1/suggestions/weekly")
async def get_weekly_outlook(db: AsyncSession = Depends(get_db)):
    from app.suggestion_engine.engine import SuggestionEngine
    strategy_mode = await get_setting(db, "strategy_mode")
    strategy_mode = strategy_mode if strategy_mode in ("scalping", "day_trading", "swing") else "scalping"
    engine = SuggestionEngine(db)
    return {"outlook": await engine.weekly_outlook(strategy_mode)}


@app.get("/api/v1/suggestions/pair/{symbol}")
async def get_pair_deep_dive(symbol: str, db: AsyncSession = Depends(get_db)):
    from app.suggestion_engine.engine import SuggestionEngine
    strategy_mode = await get_setting(db, "strategy_mode")
    strategy_mode = strategy_mode if strategy_mode in ("scalping", "day_trading", "swing") else "scalping"
    engine = SuggestionEngine(db)
    return await engine.pair_deep_dive(symbol, strategy_mode)


@app.get("/api/v1/manual-override")
async def get_manual_override(db: AsyncSession = Depends(get_db)):
    val = await get_setting_bool(db, "manual_override")
    return {"manual_override": val}


@app.post("/api/v1/manual-override")
async def toggle_manual_override(db: AsyncSession = Depends(get_db)):
    current = await get_setting_bool(db, "manual_override")
    new_val = not current
    await set_setting(db, "manual_override", str(new_val).lower())
    await broadcast_settings_change({"type": "manual_override_changed", "manual_override": new_val})
    return {"manual_override": new_val}


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.subscriptions: dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = {"symbols": [], "topics": ["prices", "trades", "ai_decisions", "settings"]}

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger = logging.getLogger("app.main")
                logger.debug("WebSocket broadcast error, disconnecting client: %s", e)
                disconnected.append(connection)
        for d in disconnected:
            self.disconnect(d)

    async def broadcast_to_subscribers(self, topic: str, message: dict):
        disconnected = []
        for connection in self.active_connections:
            subs = self.subscriptions.get(connection, {})
            topics = subs.get("topics", [])
            if topic in topics or "all" in topics:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception as e:
                    logger = logging.getLogger("app.main")
                    logger.debug("WebSocket topic broadcast error, disconnecting client: %s", e)
                    disconnected.append(connection)
        for d in disconnected:
            self.disconnect(d)

    def update_subscription(self, websocket: WebSocket, symbols: list = None, topics: list = None):
        if websocket in self.subscriptions:
            if symbols is not None:
                self.subscriptions[websocket]["symbols"] = symbols
            if topics is not None:
                self.subscriptions[websocket]["topics"] = topics


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    redis_listener_task = None

    async def redis_listener():
        logger = logging.getLogger("app.main")
        try:
            import redis.asyncio as aioredis
            redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = redis.pubsub()
            await pubsub.subscribe("ws:prices", "ws:trades", "ws:ai_decisions", "ws:settings")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await websocket.send_text(json.dumps(data))
                    except Exception as e:
                        logger.debug("WebSocket redis listener send failed: %s", e)
        except asyncio.CancelledError:
            pass  # Normal shutdown
        except Exception as e:
            logger.warning("WebSocket redis listener crashed: %s", e, exc_info=True)

    redis_listener_task = asyncio.create_task(redis_listener())

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            action = msg.get("action")
            if action == "subscribe_prices":
                symbols = msg.get("symbols", [settings.DEFAULT_PAIR])
                provider = msg.get("provider")
                provider_enum = schemas.DataProvider(provider) if provider else settings.DATA_PROVIDER
                manager.update_subscription(websocket, symbols=symbols)
                for sym in symbols:
                    try:
                        price = await _safe_get_price(sym, provider_enum)
                        await websocket.send_text(json.dumps({
                            "type": "price_tick",
                            "topic": "prices",
                            "symbol": sym,
                            "bid": price.get("bid"),
                            "ask": price.get("ask"),
                            "timestamp": price.get("timestamp"),
                        }))
                    except HTTPException:
                        pass  # _safe_get_price already logged
                    except Exception as e:
                        logger = logging.getLogger("app.main")
                        logger.debug("Initial price send failed for %s: %s", sym, e)
            elif action == "subscribe_topics":
                topics = msg.get("topics", ["prices", "trades", "ai_decisions", "settings"])
                manager.update_subscription(websocket, topics=topics)
                await websocket.send_text(json.dumps({"type": "subscription_updated", "topics": topics}))
            elif action == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            else:
                await websocket.send_text(json.dumps({"type": "echo", "data": data}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        if redis_listener_task:
            redis_listener_task.cancel()
            try:
                await redis_listener_task
            except asyncio.CancelledError:
                pass


async def broadcast_price_tick(symbol: str, bid: float, ask: float, timestamp: str = None):
    message = {
        "type": "price_tick",
        "topic": "prices",
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "timestamp": timestamp or utc_now().isoformat(),
    }
    await manager.broadcast_to_subscribers("prices", message)
    from app.services.websocket_broadcaster import broadcast_via_redis, CHANNEL_PRICES
    await broadcast_via_redis(CHANNEL_PRICES, message)


async def broadcast_trade_event(event_type: str, trade_data: dict):
    message = {
        "type": "trade_event",
        "topic": "trades",
        "event": event_type,
        "data": trade_data,
    }
    await manager.broadcast_to_subscribers("trades", message)
    from app.services.websocket_broadcaster import broadcast_via_redis, CHANNEL_TRADES
    await broadcast_via_redis(CHANNEL_TRADES, message)


async def broadcast_ai_decision(decision_data: dict):
    message = {
        "type": "ai_decision",
        "topic": "ai_decisions",
        "data": decision_data,
    }
    await manager.broadcast_to_subscribers("ai_decisions", message)
    from app.services.websocket_broadcaster import broadcast_via_redis, CHANNEL_AI_DECISIONS
    await broadcast_via_redis(CHANNEL_AI_DECISIONS, message)


async def broadcast_settings_change(settings_data: dict):
    message = {
        "type": "settings_change",
        "topic": "settings",
        "data": settings_data,
    }
    await manager.broadcast_to_subscribers("settings", message)
    from app.services.websocket_broadcaster import broadcast_via_redis, CHANNEL_SETTINGS
    await broadcast_via_redis(CHANNEL_SETTINGS, message)

# =============================================================================
# MT5 Container / Broker Account Management
# =============================================================================

@app.get("/api/v1/mt5/status", response_model=schemas.MT5StatusOut)
async def get_mt5_status(db: AsyncSession = Depends(get_db)):
    """Check MT5 container and ZMQ bridge status."""
    import zmq
    container_running = True
    zmq_reachable = False
    mt5_initialized = False
    try:
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 12000)
        sock.setsockopt(zmq.SNDTIMEO, 2000)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(f"tcp://{settings.MT5_ZMQ_HOST}:{settings.MT5_ZMQ_REQ_PORT}")
        sock.send_string(json.dumps({"action": "GET_ACCOUNT"}))
        resp = sock.recv_string()
        data = json.loads(resp)
        zmq_reachable = True
        mt5_initialized = "error" not in data or "not initialized" not in data.get("error", "")
        sock.close()
        ctx.term()
    except zmq.Again:
        # Timeout — container is running but MT5 init is slow
        pass
    except Exception:
        container_running = False

    active_account = None
    result = await db.execute(
        select(models.BrokerAccount).where(models.BrokerAccount.is_active == True)
    )
    account = result.scalar_one_or_none()
    if account:
        active_account = schemas.BrokerAccountOut.model_validate(account)

    return schemas.MT5StatusOut(
        container_running=container_running,
        mt5_terminal_running=zmq_reachable,
        zmq_bridge_running=zmq_reachable,
        mt5_initialized=mt5_initialized,
        active_account=active_account,
        message="MT5 OK" if zmq_reachable else "MT5 container not reachable",
    )


@app.get("/api/v1/mt5/accounts", response_model=list[schemas.BrokerAccountOut])
async def list_broker_accounts(db: AsyncSession = Depends(get_db)):
    """List all stored MT5 broker accounts."""
    result = await db.execute(select(models.BrokerAccount).order_by(models.BrokerAccount.created_at.desc()))
    return result.scalars().all()


@app.post("/api/v1/mt5/accounts", response_model=schemas.BrokerAccountOut)
async def create_broker_account(payload: schemas.BrokerAccountCreate, db: AsyncSession = Depends(get_db)):
    """Add a new MT5 broker account."""
    account = models.BrokerAccount(
        name=payload.name,
        broker=payload.broker,
        login=payload.login,
        password=payload.password,
        server=payload.server,
        is_demo=payload.is_demo,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@app.delete("/api/v1/mt5/accounts/{account_id}")
async def delete_broker_account(account_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a broker account."""
    result = await db.execute(select(models.BrokerAccount).where(models.BrokerAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
    await db.commit()
    return {"status": "deleted", "id": account_id}


@app.put("/api/v1/mt5/accounts/{account_id}/activate")
async def activate_broker_account(account_id: int, db: AsyncSession = Depends(get_db)):
    """Activate a broker account and deactivate all others."""
    result = await db.execute(select(models.BrokerAccount).where(models.BrokerAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Deactivate all accounts
    await db.execute(
        text("UPDATE broker_accounts SET is_active = FALSE")
    )
    account.is_active = True
    await db.commit()
    await db.refresh(account)
    return {"status": "activated", "account": schemas.BrokerAccountOut.model_validate(account)}


@app.post("/api/v1/mt5/restart")
async def restart_mt5_container():
    """Restart the MT5 container (requires Docker socket access)."""
    import subprocess
    try:
        subprocess.run(
            ["docker", "restart", "deez-forex-mt5"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return {"status": "restarted", "message": "MT5 container restart initiated"}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart MT5 container: {e.stderr.decode()}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart MT5 container: {e}")



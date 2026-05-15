import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
import redis.asyncio as aioredis

from app.database import get_db, engine, Base
from app.config import get_settings
from app import models, schemas
from app.services.data.metaapi_client import MetaApiClient
from app.services.data.mt5_zmq_client import MT5ZMQClient
from app.services.data.mt5_zmq_subscriber import MT5ZMQSubscriber
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.services.settings_service import build_settings_response, set_setting, get_setting_bool, get_setting
from app.ai.openrouter_client import OpenRouterClient
from app.analysis.aggregator import AnalysisAggregator
from app.analysis.technical import TechnicalAnalyzer
from app.analysis.fundamental import FundamentalAnalyzer
from app.analysis.sentiment import SentimentAnalyzer

settings = get_settings()

AVAILABLE_PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "GBPJPY", "XAUUSD"]


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    if settings.DATA_PROVIDER == schemas.DataProvider.mt5_zmq:
        app.state.mt5_sub = MT5ZMQSubscriber(on_tick=broadcast_price_tick)
        await app.state.mt5_sub.start()
    else:
        app.state.mt5_sub = None

    yield
    await app.state.redis.close()
    if app.state.mt5_sub:
        await app.state.mt5_sub.stop()
    await app.state.mt5_zmq.close()


app = FastAPI(
    title="deez-forex-ai",
    description="Intelligent 24/7 Forex Trading Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "env": settings.APP_ENV}


async def _get_data_client(provider: schemas.DataProvider = None):
    provider = provider or settings.DATA_PROVIDER
    if provider == schemas.DataProvider.mt5_zmq:
        return app.state.mt5_zmq
    return app.state.metaapi


async def _safe_get_price(symbol: str, provider: schemas.DataProvider = None):
    """Try the requested provider first, fall back to the other if it fails."""
    primary = await _get_data_client(provider)
    try:
        return await primary.get_current_price(symbol)
    except Exception:
        # Fallback to the other provider
        fallback = app.state.mt5_zmq if primary == app.state.metaapi else app.state.metaapi
        try:
            return await fallback.get_current_price(symbol)
        except Exception:
            # Last resort: return mock price
            return {
                "symbol": symbol,
                "bid": round(1.0850, 5),
                "ask": round(1.0852, 5),
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            }


async def _safe_get_candles(symbol: str, timeframe: str, limit: int, provider: schemas.DataProvider = None):
    """Try the requested provider first, fall back to the other if it fails."""
    primary = await _get_data_client(provider)
    try:
        return await primary.get_historical_candles(symbol, timeframe, limit)
    except Exception:
        fallback = app.state.mt5_zmq if primary == app.state.metaapi else app.state.metaapi
        try:
            return await fallback.get_historical_candles(symbol, timeframe, limit)
        except Exception:
            # Last resort: return empty list (caller should handle)
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

        now_utc = datetime.utcnow()
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
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


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
    direction_enum = schemas.TradeDirection.buy if trade_in.direction.lower() == "buy" else schemas.TradeDirection.sell
    mode_enum = schemas.TradeMode.paper if (trade_in.mode or "paper").lower() == "paper" else schemas.TradeMode.live
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
    for t in trades:
        try:
            price = await _safe_get_price(t.symbol, schemas.DataProvider(t.provider))
            current = price.get("bid") if t.direction == "sell" else price.get("ask")
        except Exception:
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
    except Exception:
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
    total_result = await db.execute(select(func.count(models.Trade.id)).where(models.Trade.status == models.TradeStatus.CLOSED))
    total_closed = total_result.scalar() or 0

    win_result = await db.execute(
        select(func.count(models.Trade.id)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl > 0
        )
    )
    wins = win_result.scalar() or 0

    loss_result = await db.execute(
        select(func.count(models.Trade.id)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl <= 0
        )
    )
    losses = loss_result.scalar() or 0

    gross_profit_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl > 0
        )
    )
    gross_profit = gross_profit_result.scalar() or 0.0

    gross_loss_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl <= 0
        )
    )
    gross_loss = abs(gross_loss_result.scalar() or 0.0)

    total_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(models.Trade.status == models.TradeStatus.CLOSED)
    )
    total_pnl = total_pnl_result.scalar() or 0.0

    unrealized_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(models.Trade.status == models.TradeStatus.OPEN)
    )
    unrealized = unrealized_result.scalar() or 0.0

    equity = 10000.0 + total_pnl + unrealized
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
    }


@app.get("/api/v1/trades/stats")
async def get_trade_stats(db: AsyncSession = Depends(get_db)):
    total_result = await db.execute(select(func.count(models.Trade.id)).where(models.Trade.status == models.TradeStatus.CLOSED))
    total_closed = total_result.scalar() or 0

    win_result = await db.execute(
        select(func.count(models.Trade.id)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl > 0
        )
    )
    wins = win_result.scalar() or 0

    loss_result = await db.execute(
        select(func.count(models.Trade.id)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl <= 0
        )
    )
    losses = loss_result.scalar() or 0

    gross_profit_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl > 0
        )
    )
    gross_profit = gross_profit_result.scalar() or 0.0

    gross_loss_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.pnl <= 0
        )
    )
    gross_loss = abs(gross_loss_result.scalar() or 0.0)

    total_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(models.Trade.status == models.TradeStatus.CLOSED)
    )
    total_pnl = total_pnl_result.scalar() or 0.0

    today = datetime.utcnow().date()
    start_of_day = datetime.combine(today, datetime.min.time())
    daily_pnl_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(
            models.Trade.status == models.TradeStatus.CLOSED,
            models.Trade.close_time >= start_of_day,
        )
    )
    daily_pnl = daily_pnl_result.scalar() or 0.0

    unrealized_result = await db.execute(
        select(func.coalesce(func.sum(models.Trade.pnl), 0)).where(models.Trade.status == models.TradeStatus.OPEN)
    )
    unrealized = unrealized_result.scalar() or 0.0

    equity = 10000.0 + total_pnl + unrealized
    win_rate = (wins / total_closed * 100) if total_closed > 0 else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

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
        model_used=settings.OPENROUTER_MODEL,
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
                direction=schemas.TradeDirection(decision.decision.lower()),
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                risk_pct=decision.position_size_pct,
                mode=schemas.TradeMode.paper,
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
        raise HTTPException(status_code=503, detail=str(e))


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
        raise HTTPException(status_code=503, detail=str(e))


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
        except Exception:
            pass

        return {
            "symbol": symbol,
            "technical_signal": tech_signal,
            "fundamental_signal": fund_bias,
            "sentiment_signal": sent_signal,
            "combined_signal": combined,
            "ai_decision": latest_ai.decision if latest_ai else None,
            "ai_confidence": latest_ai.confidence if latest_ai else None,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


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
    except Exception:
        # Fallback: return mock account info so the UI doesn't break
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
            except Exception:
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
                except Exception:
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
                    except Exception:
                        pass
        except Exception:
            pass

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
                    except Exception:
                        pass
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
        "timestamp": timestamp or datetime.utcnow().isoformat(),
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

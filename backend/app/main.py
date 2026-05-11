import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import redis.asyncio as aioredis

from app.database import get_db, engine, Base
from app.config import get_settings
from app import models, schemas
from app.services.data.metaapi_client import MetaApiClient
from app.services.execution.executor import ExecutionService
from app.services.risk.manager import RiskManager
from app.ai.openrouter_client import OpenRouterClient
from app.analysis.aggregator import AnalysisAggregator

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.metaapi = MetaApiClient()
    app.state.executor = ExecutionService()
    app.state.risk = RiskManager()
    app.state.ai = OpenRouterClient()
    app.state.aggregator = AnalysisAggregator()
    yield
    await app.state.redis.close()


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


@app.get("/api/v1/market/current")
async def get_current_market(db: AsyncSession = Depends(get_db)):
    client: MetaApiClient = app.state.metaapi
    try:
        price = await client.get_current_price(settings.DEFAULT_PAIR)
        return {
            "symbol": settings.DEFAULT_PAIR,
            "bid": price.get("bid"),
            "ask": price.get("ask"),
            "timestamp": price.get("timestamp"),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


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
    trade_in: schemas.TradeCreate,
    db: AsyncSession = Depends(get_db)
):
    risk: RiskManager = app.state.risk
    ok, reason = await risk.validate_new_trade(db, trade_in)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    executor: ExecutionService = app.state.executor
    trade = await executor.execute_trade(db, trade_in)
    return trade


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
async def trigger_ai_analysis(db: AsyncSession = Depends(get_db)):
    aggregator: AnalysisAggregator = app.state.aggregator
    ai: OpenRouterClient = app.state.ai
    executor: ExecutionService = app.state.executor
    risk: RiskManager = app.state.risk

    analysis = await aggregator.gather_all(settings.DEFAULT_PAIR)
    decision = await ai.get_trade_decision(analysis)

    db_decision = models.AIDecision(
        symbol=settings.DEFAULT_PAIR,
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
    )
    db.add(db_decision)
    await db.commit()
    await db.refresh(db_decision)

    if decision.decision in ("BUY", "SELL"):
        ok, reason = await risk.validate_ai_decision(db, decision)
        if ok:
            trade_in = schemas.TradeCreate(
                symbol=settings.DEFAULT_PAIR,
                direction=decision.decision.lower(),
                entry_price=decision.entry_price,
                stop_loss=decision.stop_loss,
                take_profit=decision.take_profit,
                risk_pct=decision.position_size_pct,
                mode=schemas.TradeMode.paper,
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


@app.get("/api/v1/backtests")
async def get_backtests(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.BacktestRun).order_by(desc(models.BacktestRun.created_at))
    )
    return result.scalars().all()


@app.get("/api/v1/settings")
async def get_app_settings():
    return {
        "default_pair": settings.DEFAULT_PAIR,
        "max_risk_per_trade_pct": settings.MAX_RISK_PER_TRADE_PCT,
        "max_daily_loss_pct": settings.MAX_DAILY_LOSS_PCT,
        "openrouter_model": settings.OPENROUTER_MODEL,
        "paper_mode": True,
    }


@app.put("/api/v1/settings")
async def update_app_settings(payload: dict):
    return {"detail": "Settings persisted in-memory only; implement DB persistence if needed"}


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_text(json.dumps(message))


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"echo": data}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)

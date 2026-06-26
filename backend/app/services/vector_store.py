"""Qdrant vector store client for market state snapshots."""
import json
import logging
import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.vector_store")
COLLECTION_NAME = "market_state_snapshots"
VECTOR_SIZE = 128  # Expanded: technical + sentiment + macro + regime + session


def _encode_snapshot(snapshot: Dict[str, Any]) -> List[float]:
    """Convert a full analysis snapshot into a 128-dim float vector."""
    tech = snapshot.get("technical", snapshot) if isinstance(snapshot, dict) else {}
    tfs = tech.get("timeframes", {})

    def _tf_vec(tf_name: str) -> List[float]:
        tf = tfs.get(tf_name, {})
        ind = tf.get("indicators", {})
        return [
            float(ind.get("rsi14", 50)),
            float(ind.get("macd", 0)),
            float(ind.get("macd_signal", 0)),
            float(ind.get("atr", 0)),
            float(ind.get("bb_upper", 0)),
            float(ind.get("bb_lower", 0)),
            float(ind.get("sma20", 0)),
            float(ind.get("ema50", 0)),
        ]

    m15 = _tf_vec("M15")
    h1 = _tf_vec("H1")
    h4 = _tf_vec("H4")
    d1 = _tf_vec("D1")

    # Session one-hot (asia, london, ny, london_ny_overlap)
    session = tech.get("session", "unknown")
    session_vec = [1.0 if session == s else 0.0 for s in ["asia", "london", "ny", "london_ny_overlap"]]

    # Sentiment / macro placeholders (pad to 128)
    sentiment = tech.get("sentiment", {})
    sentiment_vec = [
        float(sentiment.get("composite", 0)),
        float(sentiment.get("finbert", 0)),
        float(sentiment.get("myfxbook", 0)),
        float(sentiment.get("cot", 0)),
    ]

    macro = tech.get("macro", {})
    macro_vec = [
        float(macro.get("nonfarm_momentum", 0)),
        float(macro.get("fed_rate_change", 0)),
        float(macro.get("cpi_yoy", 0)),
        float(macro.get("yield_spread", 0)),
        float(macro.get("dxy_trend", 0)),
        float(macro.get("gold_trend", 0)),
        float(macro.get("vix_level", 0)),
        float(macro.get("spy_correlation", 0)),
    ]

    vec = m15 + h1 + h4 + d1 + session_vec + sentiment_vec + macro_vec
    # Pad or truncate to VECTOR_SIZE
    if len(vec) < VECTOR_SIZE:
        vec += [0.0] * (VECTOR_SIZE - len(vec))
    return vec[:VECTOR_SIZE]


class VectorStore:
    """Synchronous Qdrant client for non-async contexts."""

    def __init__(self):
        self.client = QdrantClient(url=settings.QDRANT_URL, timeout=10)
        self._ensure_collection()

    def _ensure_collection(self):
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]
        if COLLECTION_NAME not in names:
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            return
        info = self.client.get_collection(COLLECTION_NAME)
        current_size = info.config.params.vectors.size if info.config.params.vectors else 0
        if current_size != VECTOR_SIZE:
            logger.warning(
                "Qdrant collection %s has vector size %d, expected %d. Recreating...",
                COLLECTION_NAME, current_size, VECTOR_SIZE,
            )
            self.client.delete_collection(COLLECTION_NAME)
            self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    def upsert_snapshot(self, point_id: str, snapshot: Dict[str, Any], payload: Dict[str, Any]):
        vector = _encode_snapshot(snapshot)
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def search_similar(self, snapshot: Dict[str, Any], limit: int = 10, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        vector = _encode_snapshot(snapshot)
        results = self.client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=limit,
            with_payload=True,
        )
        out = []
        for r in results:
            payload = r.payload or {}
            if min_confidence and (payload.get("confidence") or 0) < min_confidence:
                continue
            out.append({
                "id": r.id,
                "score": r.score,
                "symbol": payload.get("symbol"),
                "decision": payload.get("decision"),
                "confidence": payload.get("confidence"),
                "outcome_pnl": payload.get("outcome_pnl"),
                "outcome_status": payload.get("outcome_status"),
                "strategy_mode": payload.get("strategy_mode"),
                "timestamp": payload.get("timestamp"),
            })
        return out

    def update_outcome(self, point_id: str, pnl: float, status: str):
        try:
            self.client.set_payload(
                collection_name=COLLECTION_NAME,
                points=[point_id],
                payload={"outcome_pnl": pnl, "outcome_status": status},
            )
        except Exception as e:
            logger.error("Failed to update outcome for point %s: %s", point_id, e, exc_info=True)


class AsyncVectorStore:
    """Async-native Qdrant client using AsyncQdrantClient."""

    def __init__(self):
        from qdrant_client import AsyncQdrantClient
        self.client = AsyncQdrantClient(url=settings.QDRANT_URL, timeout=10)

    async def _ensure_collection(self):
        collections = (await self.client.get_collections()).collections
        names = [c.name for c in collections]
        if COLLECTION_NAME not in names:
            await self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            return
        info = await self.client.get_collection(COLLECTION_NAME)
        current_size = info.config.params.vectors.size if info.config.params.vectors else 0
        if current_size != VECTOR_SIZE:
            logger.warning(
                "Qdrant collection %s has vector size %d, expected %d. Recreating...",
                COLLECTION_NAME, current_size, VECTOR_SIZE,
            )
            await self.client.delete_collection(COLLECTION_NAME)
            await self.client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    async def upsert_snapshot(self, point_id: str, snapshot: Dict[str, Any], payload: Dict[str, Any]):
        await self._ensure_collection()
        vector = _encode_snapshot(snapshot)
        await self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    async def search_similar(self, snapshot: Dict[str, Any], limit: int = 10, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        await self._ensure_collection()
        vector = _encode_snapshot(snapshot)
        results = await self.client.search(
            collection_name=COLLECTION_NAME,
            query_vector=vector,
            limit=limit,
            with_payload=True,
        )
        out = []
        cutoff = os.environ.get("BACKTEST_DATE_CUTOFF")
        for r in results:
            payload = r.payload or {}
            if min_confidence and (payload.get("confidence") or 0) < min_confidence:
                continue
            if cutoff:
                ts = payload.get("timestamp")
                if ts and str(ts) > cutoff:
                    continue
            out.append({
                "id": r.id,
                "score": r.score,
                "symbol": payload.get("symbol"),
                "decision": payload.get("decision"),
                "confidence": payload.get("confidence"),
                "outcome_pnl": payload.get("outcome_pnl"),
                "outcome_status": payload.get("outcome_status"),
                "strategy_mode": payload.get("strategy_mode"),
                "timestamp": payload.get("timestamp"),
            })
        return out

    async def update_outcome(self, point_id: str, pnl: float, status: str):
        try:
            await self.client.set_payload(
                collection_name=COLLECTION_NAME,
                points=[point_id],
                payload={"outcome_pnl": pnl, "outcome_status": status},
            )
        except Exception as e:
            logger.error("Failed to update outcome for point %s: %s", point_id, e, exc_info=True)

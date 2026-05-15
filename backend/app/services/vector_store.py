"""Qdrant vector store client for market state snapshots."""
import json
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import get_settings

settings = get_settings()
COLLECTION_NAME = "market_state_snapshots"
VECTOR_SIZE = 32  # Number of technical indicator features we vectorize


class VectorStore:
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

    def _encode_snapshot(self, snapshot: Dict[str, Any]) -> List[float]:
        """Convert a technical snapshot into a fixed-size float vector."""
        tech = snapshot.get("technical", {})
        tfs = tech.get("timeframes", {})
        # Use the smallest timeframe available
        tf_name = next(iter(tfs.keys()), "1h")
        tf = tfs.get(tf_name, {})
        ind = tf.get("indicators", {})

        # Normalize features to roughly -1..1 range
        features = [
            1.0 if tech.get("overall_signal") == "bullish" else -1.0 if tech.get("overall_signal") == "bearish" else 0.0,
            (ind.get("rsi_14", 50) - 50) / 50.0,
            (ind.get("ema_9", 1.0) - ind.get("ema_21", 1.0)) * 10000,  # pip difference
            (ind.get("macd", 0.0) or 0.0) * 10000,
            (ind.get("macd_hist", 0.0) or 0.0) * 10000,
            (ind.get("bb_upper", 0.0) or 0.0) - (ind.get("bb_lower", 0.0) or 0.0),  # bandwidth
            (ind.get("atr_14", 0.0) or 0.0) * 10000,
            (ind.get("vwap", 1.0) - ind.get("close", 1.0)) * 10000 if ind.get("vwap") else 0.0,
            (ind.get("adx_14", 0.0) or 0.0) / 50.0,
            1.0 if tf.get("bb_squeeze") else 0.0,
            1.0 if tf.get("divergence") == "bullish_divergence" else -1.0 if tf.get("divergence") == "bearish_divergence" else 0.0,
            (ind.get("close", 1.0) - (ind.get("support", 1.0) or ind.get("close", 1.0))) * 10000,
            (ind.get("resistance", 1.0) or ind.get("close", 1.0)) - ind.get("close", 1.0) * 10000,
        ]
        # Pad or truncate to VECTOR_SIZE
        if len(features) < VECTOR_SIZE:
            features.extend([0.0] * (VECTOR_SIZE - len(features)))
        return features[:VECTOR_SIZE]

    def upsert_snapshot(self, point_id: str, snapshot: Dict[str, Any], payload: Dict[str, Any]):
        vector = self._encode_snapshot(snapshot)
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def search_similar(self, snapshot: Dict[str, Any], limit: int = 10, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        vector = self._encode_snapshot(snapshot)
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
        """Update the outcome of a previously stored snapshot."""
        try:
            self.client.set_payload(
                collection_name=COLLECTION_NAME,
                points=[point_id],
                payload={"outcome_pnl": pnl, "outcome_status": status},
            )
        except Exception:
            pass

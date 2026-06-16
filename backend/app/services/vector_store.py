"""Qdrant vector store client for market state snapshots."""
import json
import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.vector_store")
COLLECTION_NAME = "market_state_snapshots"
VECTOR_SIZE = 128  # Expanded: technical + sentiment + macro + regime + session


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
            return
        # Check if existing collection has wrong vector size (migration from 32 -> 128)
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

    def _encode_snapshot(self, snapshot: Dict[str, Any]) -> List[float]:
        """Convert a full analysis snapshot into a 128-dim float vector."""
        tech = snapshot.get("technical", snapshot) if isinstance(snapshot, dict) else {}
        tfs = tech.get("timeframes", {})

        def _tf_vec(tf_name: str) -> List[float]:
            tf = tfs.get(tf_name, {})
            ind = tf.get("indicators", {})
            return [
                1.0 if tf.get("signal") == "bullish" else -1.0 if tf.get("signal") == "bearish" else 0.0,
                (ind.get("rsi_14", 50) - 50) / 50.0,
                (ind.get("ema_9", 1.0) - ind.get("ema_21", 1.0)) * 10000,
                (ind.get("macd", 0.0) or 0.0) * 10000,
                (ind.get("macd_hist", 0.0) or 0.0) * 10000,
                ((ind.get("bb_upper", 0.0) or 0.0) - (ind.get("bb_lower", 0.0) or 0.0)) * 10000,
                (ind.get("atr_14", 0.0) or 0.0) * 10000,
                (ind.get("adx_14", 0.0) or 0.0) / 50.0,
                1.0 if tf.get("bb_squeeze") else 0.0,
                1.0 if tf.get("divergence") == "bullish_divergence" else -1.0 if tf.get("divergence") == "bearish_divergence" else 0.0,
            ]

        # Per-timeframe signals (3 TFs x 10 features = 30)
        tf1 = _tf_vec("1m") if "1m" in tfs else _tf_vec("5m") if "5m" in tfs else [0.0] * 10
        tf2 = _tf_vec("15m") if "15m" in tfs else _tf_vec("30m") if "30m" in tfs else [0.0] * 10
        tf3 = _tf_vec("1h") if "1h" in tfs else _tf_vec("4h") if "4h" in tfs else [0.0] * 10

        # Fundamental scores (5 features)
        fund = snapshot.get("fundamental", {})
        fundamental_vec = [
            1.0 if fund.get("event_risk") == "high" else 0.5 if fund.get("event_risk") == "medium" else 0.0,
            (fund.get("interest_spread", 0.0) or 0.0) * 100,
            (fund.get("economic_surprise", 0.0) or 0.0) / 5.0,
            1.0 if fund.get("cb_meeting_proximity", 0) < 7 else 0.0,
            (fund.get("cpi_yoy", 0.0) or 0.0) / 10.0,
        ]

        # Sentiment scores (5 features)
        sent = snapshot.get("sentiment", {})
        sentiment_vec = [
            (sent.get("finbert_score", 0.0) or 0.0),
            ((sent.get("retail_long_pct", 50) or 50) - 50) / 50.0,
            ((sent.get("cot_net", 0) or 0) / 50000.0),
            (sent.get("news_count", 0) or 0) / 20.0,
            1.0 if sent.get("extreme_sentiment") else 0.0,
        ]

        # Macro scores (5 features)
        macro = snapshot.get("macro", {})
        macro_vec = [
            (macro.get("dxy_zscore", 0.0) or 0.0) / 3.0,
            (macro.get("vix_level", 15) or 15) / 30.0,
            (macro.get("yield_curve", 0.0) or 0.0) / 2.0,
            (macro.get("risk_on_score", 0.0) or 0.0),
            (macro.get("hy_spread", 0.0) or 0.0) / 500.0,
        ]

        # Session / time cyclical encoding (4 features)
        from app.utils.time import utc_now
        from app.services.sessions import classify_session
        now = utc_now()
        hour = now.hour
        session = classify_session(now)
        session_map = {"asia": 0, "london": 1, "ny": 2, "overlap": 3}
        session_idx = session_map.get(session, 0)
        session_onehot = [1.0 if i == session_idx else 0.0 for i in range(4)]
        time_vec = [
            session_onehot[0],
            session_onehot[1],
            session_onehot[2],
            session_onehot[3],
            (hour / 24.0) * 2 - 1,  # normalize to -1..1
        ]

        # Regime label (one-hot-ish, 4 features)
        regime = snapshot.get("regime", "unknown")
        regime_map = {"trending": 0, "ranging": 1, "breakout": 2, "reversal": 3}
        regime_idx = regime_map.get(regime, 0)
        regime_onehot = [1.0 if i == regime_idx else 0.0 for i in range(4)]
        regime_vec = [
            regime_onehot[0],
            regime_onehot[1],
            regime_onehot[2],
            regime_onehot[3],
        ]

        # Trade setup context (5 features)
        setup = snapshot.get("setup", {})
        setup_vec = [
            1.0 if setup.get("direction") == "buy" else -1.0 if setup.get("direction") == "sell" else 0.0,
            (setup.get("confidence", 0.5) or 0.5) * 2 - 1,
            (setup.get("rr", 1.0) or 1.0) / 3.0,
            (setup.get("atr_pct", 0.0) or 0.0) * 100,
            1.0 if setup.get("news_proximity") else 0.0,
        ]

        # Combine all vectors
        features = (
            tf1 + tf2 + tf3 +
            fundamental_vec + sentiment_vec + macro_vec +
            time_vec + regime_vec + setup_vec
        )

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
        except Exception as e:
            logger.error("Failed to update outcome for point %s: %s", point_id, e, exc_info=True)

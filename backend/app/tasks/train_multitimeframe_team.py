"""Combined multi-timeframe + v2 AI Team training pipeline.

Trains two models:
  1. EntryQualityModel on multi-timeframe technical features
  2. TeamMetaModel on analyst opinion patterns
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import select

from app.database import get_celery_session
from app import models
from app.services.ml.multitimeframe_features import compute_multitimeframe_features
from app.services.ml.team_meta_model import TeamMetaModel
from app.services.ml.entry_model import EntryQualityModel
from app.services.feature_store import FeatureStore

logger = logging.getLogger("app.tasks.train_multitimeframe_team")


@shared_task(
    bind=True,
    time_limit=600,
    soft_time_limit=480,
    queue="data_ingestion",
)
def train_multitimeframe_and_team(self):
    """Retrain both entry model and team meta-model on latest data."""
    async def _run():
        async with get_celery_session()() as db:
            since = datetime.now(timezone.utc) - timedelta(days=180)
            result = await db.execute(
                select(models.Trade)
                .where(models.Trade.status == models.TradeStatus.CLOSED)
                .where(models.Trade.close_time >= since)
                .where(models.Trade.ai_decision_id.isnot(None))
                .order_by(models.Trade.close_time)
                .limit(3000)
            )
            trades = result.scalars().all()
            logger.info("Found %d closed trades with decisions", len(trades))

            if len(trades) < 100:
                logger.warning("Insufficient data (%d trades), skipping training", len(trades))
                return {"status": "skipped", "trades": len(trades)}

            # --- Multi-timeframe entry model data ---
            entry_decisions = []
            # --- Team meta-model data ---
            team_data = []

            for t in trades:
                d_result = await db.execute(
                    select(models.AIDecision)
                    .where(models.AIDecision.id == t.ai_decision_id)
                )
                decision = d_result.scalar_one_or_none()
                if not decision:
                    continue

                label = 1 if (t.pnl or 0) > 0 else 0

                # 1. Multi-timeframe features
                try:
                    mt_feats = await compute_multitimeframe_features(
                        db, t.symbol, decision.created_at or t.created_at
                    )
                except Exception as exc:
                    logger.debug("MT feature compute failed for trade %d: %s", t.id, exc)
                    mt_feats = {}

                # 2. Base analysis features (from stored snapshots)
                analysis = {
                    "technical": decision.technical_snapshot or {},
                    "fundamental": decision.fundamental_snapshot or {},
                    "sentiment": decision.sentiment_snapshot or {},
                    "macro": decision.daily_bias or {},
                }
                base_feats = FeatureStore.compute_entry_features(analysis)

                # Combine
                combined_feats = {**base_feats, **mt_feats}
                entry_decisions.append({
                    "features": combined_feats,
                    "label": label,
                    "symbol": t.symbol,
                    "direction": t.direction,
                })

                # 3. Team meta-model features
                try:
                    from app.services.ml.team_meta_model import _extract_analyst_features, _extract_verifier_features
                    team_feats = {}
                    team_feats.update(_extract_analyst_features(decision.analyst_opinions))
                    team_feats.update(_extract_verifier_features(decision.verifier_verdict, decision.lead_model))
                    team_feats["symbol"] = t.symbol
                    team_feats["direction"] = 1 if t.direction == "buy" else 0
                    team_feats["label"] = label
                    team_data.append(team_feats)
                except Exception as exc:
                    logger.debug("Team feature extraction failed for trade %d: %s", t.id, exc)

            # Train entry model
            entry_metrics = {}
            if len(entry_decisions) >= 100:
                import pandas as pd
                entry_df = FeatureStore.export_training_set(entry_decisions)
                entry_model = EntryQualityModel()
                entry_metrics = entry_model.train(entry_df)
                logger.info("Entry model retrained: test_auc=%.3f", entry_metrics.get("test_auc", 0))
            else:
                logger.warning("Insufficient entry data: %d samples", len(entry_decisions))

            # Train team meta-model
            team_metrics = {}
            if len(team_data) >= 100:
                import pandas as pd
                team_df = pd.DataFrame(team_data)
                team_model = TeamMetaModel()
                team_metrics = team_model.train(team_df)
                logger.info("Team meta-model retrained: test_auc=%.3f", team_metrics.get("test_auc", 0))
            else:
                logger.warning("Insufficient team data: %d samples", len(team_data))

            return {
                "status": "completed",
                "trades": len(trades),
                "entry_samples": len(entry_decisions),
                "team_samples": len(team_data),
                "entry_metrics": entry_metrics,
                "team_metrics": team_metrics,
            }

    return asyncio.run(_run())

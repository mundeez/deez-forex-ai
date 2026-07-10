"""Standalone model retraining script.

Trains EntryQualityModel and TeamMetaModel on all available closed trades
in the database.  This is intended to be run after a backtest completes
(or at any point) to build model artifacts that the backtest engine can
load via _load_from_disk().

Usage:
    docker compose exec backend python /app/retrain_models.py
"""
import asyncio
import logging
import sys

import numpy as np
import pandas as pd
from sqlalchemy import select

from app import models
from app.database import get_celery_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("retrain_models")


async def retrain():
    from app.services.ml.multitimeframe_features import compute_multitimeframe_features
    from app.services.ml.team_meta_model import (
        TeamMetaModel,
        _extract_analyst_features,
        _extract_verifier_features,
    )
    from app.services.ml.entry_model import EntryQualityModel
    from app.services.feature_store import FeatureStore

    async with get_celery_session()() as db:
        result = await db.execute(
            select(models.Trade)
            .where(models.Trade.status == models.TradeStatus.CLOSED)
            .where(models.Trade.ai_decision_id.isnot(None))
            .order_by(models.Trade.close_time)
            .limit(5000)
        )
        trades = result.scalars().all()
        logger.info("Loaded %d closed trades with AI decisions", len(trades))

        if len(trades) < 50:
            logger.error("Not enough trades to train (need >=50, got %d)", len(trades))
            return

        entry_data = []
        team_data = []
        skipped = 0

        for i, t in enumerate(trades):
            d_result = await db.execute(
                select(models.AIDecision).where(models.AIDecision.id == t.ai_decision_id)
            )
            decision = d_result.scalar_one_or_none()
            if not decision:
                skipped += 1
                continue

            label = 1 if (t.pnl or 0) > 0 else 0

            # --- Entry features ---
            try:
                mt = await compute_multitimeframe_features(
                    db, t.symbol, decision.created_at or t.created_at
                )
            except Exception:
                mt = {}

            analysis = {
                "technical": decision.technical_snapshot or {},
                "fundamental": decision.fundamental_snapshot or {},
                "sentiment": decision.sentiment_snapshot or {},
                "macro": decision.daily_bias or {},
            }
            base = FeatureStore.compute_entry_features(analysis)
            entry_data.append(
                {
                    "features": {**base, **mt},
                    "label": label,
                    "symbol": t.symbol,
                    "direction": t.direction,
                }
            )

            # --- Team meta features ---
            tf = {}
            tf.update(_extract_analyst_features(decision.analyst_opinions))
            tf.update(
                _extract_verifier_features(decision.verifier_verdict, decision.lead_model)
            )
            tf["label"] = label
            team_data.append(tf)

            if (i + 1) % 200 == 0:
                logger.info(
                    "  processed %d/%d trades (skipped=%d, pos_rate=%.2f)",
                    i + 1,
                    len(trades),
                    skipped,
                    np.mean([d["label"] for d in entry_data]),
                )

        logger.info(
            "Feature extraction complete: %d entry samples, %d team samples, %d skipped",
            len(entry_data),
            len(team_data),
            skipped,
        )

        # --- Train EntryQualityModel ---
        if len(entry_data) >= 50:
            df_entry = FeatureStore.export_training_set(entry_data)
            logger.info("Entry DataFrame shape: %s", df_entry.shape)
            logger.info("Entry feature columns: %s", list(df_entry.columns)[:20])
            logger.info("Positive rate: %.3f", df_entry["label"].mean())

            entry_model = EntryQualityModel()
            entry_metrics = entry_model.train(df_entry, win_weight=1.0)
            logger.info("EntryQualityModel trained: %s", entry_metrics)

            # Per-symbol breakdown of predictions
            if entry_model.model is not None:
                df_pred = df_entry.copy()
                feats = df_pred[entry_model.feature_cols].fillna(0.0)
                df_pred["pred_proba"] = entry_model.model.predict_proba(feats)[:, 1]
                df_pred["correct"] = ((df_pred["pred_proba"] >= 0.4) == (df_pred["label"] == 1)).astype(int)
                logger.info("\n--- Entry Model Per-Symbol Performance ---")
                for sym in df_pred["symbol"].unique():
                    sub = df_pred[df_pred["symbol"] == sym]
                    wr_actual = sub["label"].mean()
                    wr_pred = (sub["pred_proba"] >= 0.4).mean()
                    acc = sub["correct"].mean()
                    logger.info(
                        "  %s: n=%d actual_wr=%.2f pred_pass_rate=%.2f accuracy=%.2f avg_proba=%.3f",
                        sym,
                        len(sub),
                        wr_actual,
                        wr_pred,
                        acc,
                        sub["pred_proba"].mean(),
                    )
        else:
            logger.warning("Not enough entry samples to train EntryQualityModel")

        # --- Train TeamMetaModel ---
        if len(team_data) >= 50:
            df_team = pd.DataFrame(team_data)
            logger.info("Team DataFrame shape: %s", df_team.shape)
            logger.info("Team feature columns: %s", list(df_team.columns))
            logger.info("Positive rate: %.3f", df_team["label"].mean())

            team_model = TeamMetaModel()
            team_metrics = team_model.train(df_team, win_weight=1.0)
            logger.info("TeamMetaModel trained: %s", team_metrics)
        else:
            logger.warning("Not enough team samples to train TeamMetaModel")

        logger.info("=" * 60)
        logger.info("RETRAINING COMPLETE")
        logger.info("=" * 60)
        logger.info("EntryQualityModel: %s", "/app/models/xgb_entry_model.pkl")
        logger.info("TeamMetaModel: %s", "/app/models/team_meta_model.pkl")


if __name__ == "__main__":
    asyncio.run(retrain())

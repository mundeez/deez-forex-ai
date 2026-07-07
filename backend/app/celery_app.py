from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "deez_forex",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.analysis_tasks", "app.tasks.execution_tasks", "app.tasks.data_tasks", "app.tasks.train_multitimeframe_team", "app.tasks.backtest_full"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task hardening: timeouts, retries, result expiration
    task_time_limit=300,
    task_soft_time_limit=240,
    task_default_retry_delay=60,
    task_max_retries=3,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    # Queue routing — keep data_ingestion and dead_letter as before;
    # add dedicated queues for execution (low-latency) and AI analysis (LLM calls).
    # The default worker still consumes all queues as a catch-all fallback.
    task_routes={
        # --- Data ingestion ---
        "app.tasks.data_tasks.ingest_dukascopy_daily": {"queue": "data_ingestion"},
        "app.tasks.data_tasks.ingest_historical_range": {"queue": "data_ingestion"},
        "app.tasks.data_tasks.detect_and_backfill_gaps": {"queue": "data_ingestion"},
        "app.tasks.data_tasks.ingest_mt5_fill": {"queue": "data_ingestion"},
        "app.tasks.data_tasks.ingest_fred_macro": {"queue": "data_ingestion"},
        "app.tasks.data_tasks.ingest_yfinance_macro": {"queue": "data_ingestion"},
        "app.tasks.data_tasks.ingest_cot_weekly": {"queue": "data_ingestion"},
        # Dead letter reprocessing goes to a separate queue to avoid blocking
        "app.tasks.data_tasks.retry_dead_letter_job": {"queue": "dead_letter"},
        # --- Execution tier: high-priority, low-latency (60-180 s tasks) ---
        "app.tasks.execution_tasks.check_open_positions": {"queue": "execution"},
        "app.tasks.execution_tasks.evaluate_exits": {"queue": "execution"},
        "app.tasks.execution_tasks.reevaluate_open_positions": {"queue": "execution"},
        "app.tasks.execution_tasks.close_eod_positions": {"queue": "execution"},
        "app.tasks.execution_tasks.close_weekend_positions": {"queue": "execution"},
        "app.tasks.analysis_tasks.run_full_analysis": {"queue": "ai_analysis"},
        "app.tasks.analysis_tasks.compute_daily_bias": {"queue": "ai_analysis"},
        # Pre-compute refresh tasks go to ai_analysis so they don't block execution
        "app.tasks.analysis_tasks.refresh_technical_snapshots": {"queue": "ai_analysis"},
        "app.tasks.analysis_tasks.refresh_sentiment_cache": {"queue": "ai_analysis"},
    },
    # M4: Dead letter queue configuration (Redis-based)
    task_reject_on_worker_lost=True,
    task_default_queue="celery",
    beat_schedule={
        "analyze-market-scalping": {
            "task": "app.tasks.analysis_tasks.run_full_analysis",
            "schedule": 14400.0,  # 4 hours — once per trading session
            "options": {"time_limit": 240, "soft_time_limit": 180},
        },
        "check-open-positions": {
            "task": "app.tasks.execution_tasks.check_open_positions",
            "schedule": 60.0,
            "options": {"time_limit": 30, "soft_time_limit": 20},
        },
        "auto-select-pairs": {
            "task": "app.tasks.analysis_tasks.auto_select_pairs",
            "schedule": 3600.0,
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "update-daily-pnl": {
            "task": "app.tasks.execution_tasks.update_daily_pnl",
            "schedule": 3600.0,
            "options": {"time_limit": 60, "soft_time_limit": 45},
        },
        "close-eod-positions": {
            "task": "app.tasks.execution_tasks.close_eod_positions",
            "schedule": crontab(hour=21, minute=30, day_of_week="mon-fri"),
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "close-weekend-positions": {
            "task": "app.tasks.execution_tasks.close_weekend_positions",
            "schedule": crontab(hour=21, minute=0, day_of_week="fri"),
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "compute-pair-performance": {
            "task": "app.tasks.execution_tasks.compute_pair_performance",
            "schedule": 3600.0,
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "compute-pattern-priors": {
            "task": "app.tasks.analysis_tasks.compute_pattern_priors",
            "schedule": 3600.0 * 6,  # every 6 hours
            "options": {"time_limit": 300, "soft_time_limit": 240},
        },
        "update-model-performance": {
            "task": "app.tasks.analysis_tasks.update_model_performance",
            "schedule": 3600.0,  # hourly
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "rolling-backtest-30d": {
            "task": "app.tasks.analysis_tasks.rolling_backtest_30d",
            "schedule": 3600.0 * 24,  # daily
            "options": {"time_limit": 300, "soft_time_limit": 240},
        },
        "daily-kpi-snapshot": {
            "task": "app.tasks.analysis_tasks.daily_kpi_snapshot",
            "schedule": crontab(hour=0, minute=0),  # midnight UTC
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "compute-daily-bias": {
            "task": "app.tasks.execution_tasks.compute_daily_bias",
            "schedule": 14400.0,
            "options": {"time_limit": 180, "soft_time_limit": 120},
        },
        "refresh-model-performance": {
            "task": "app.tasks.execution_tasks.refresh_model_performance",
            "schedule": 3600.0,
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "reevaluate-open-positions": {
            "task": "app.tasks.execution_tasks.reevaluate_open_positions",
            "schedule": 180.0,
            "options": {"time_limit": 60, "soft_time_limit": 45},
        },
        # v0.8.0 M1 — Historical data ingestion pipeline
        "ingest-dukascopy-daily": {
            "task": "app.tasks.data_tasks.ingest_dukascopy_daily",
            "schedule": crontab(hour=0, minute=5),
            "options": {"time_limit": 300, "soft_time_limit": 240},
        },
        "detect-and-backfill-gaps": {
            "task": "app.tasks.data_tasks.detect_and_backfill_gaps",
            "schedule": crontab(hour=2, minute=0, day_of_week="sun"),
            "options": {"time_limit": 300, "soft_time_limit": 240},
        },
        "ingest-mt5-fill": {
            "task": "app.tasks.data_tasks.ingest_mt5_fill",
            "schedule": 1800.0,
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        # M4: Kill stale ingestion jobs every 10 minutes
        "kill-stale-jobs": {
            "task": "app.tasks.data_tasks.kill_stale_jobs",
            "schedule": 600.0,
            "options": {"time_limit": 60, "soft_time_limit": 30},
        },
        # Sprint 1: Macro data ingestion
        "ingest-fred-macro": {
            "task": "app.tasks.data_tasks.ingest_fred_macro",
            "schedule": crontab(hour=6, minute=0),
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "ingest-yfinance-macro": {
            "task": "app.tasks.data_tasks.ingest_yfinance_macro",
            "schedule": crontab(hour=7, minute=0),
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "ingest-cot-weekly": {
            "task": "app.tasks.data_tasks.ingest_cot_weekly",
            "schedule": crontab(hour=10, minute=0, day_of_week="mon"),
            "options": {"time_limit": 300, "soft_time_limit": 240},
        },
    }
)

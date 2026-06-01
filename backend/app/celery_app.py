from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "deez_forex",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.analysis_tasks", "app.tasks.execution_tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task hardening: timeouts, retries, result expiration
    task_time_limit=300,           # 5 minutes max per task (kill if hung)
    task_soft_time_limit=240,      # 4 minutes soft limit (graceful shutdown)
    task_default_retry_delay=60,   # 1 minute between retries
    task_max_retries=3,             # Max 3 retries per task
    result_expires=3600,           # Results expire after 1 hour
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,  # Fair task distribution
    beat_schedule={
        "analyze-market-scalping": {
            "task": "app.tasks.analysis_tasks.run_full_analysis",
            "schedule": 300.0,  # Every 5 minutes for scalping/day trading
            "options": {"time_limit": 240, "soft_time_limit": 180},
        },
        "check-open-positions": {
            "task": "app.tasks.execution_tasks.check_open_positions",
            "schedule": 60.0,  # Every minute for SL/TP + time-based exit
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
            "schedule": 3600.0,  # Every hour
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "compute-daily-bias": {
            "task": "app.tasks.execution_tasks.compute_daily_bias",
            "schedule": 14400.0,  # Every 4 hours
            "options": {"time_limit": 180, "soft_time_limit": 120},
        },
        "refresh-model-performance": {
            "task": "app.tasks.execution_tasks.refresh_model_performance",
            "schedule": 3600.0,  # Every hour
            "options": {"time_limit": 120, "soft_time_limit": 90},
        },
        "reevaluate-open-positions": {
            "task": "app.tasks.execution_tasks.reevaluate_open_positions",
            "schedule": 180.0,  # Every 3 minutes
            "options": {"time_limit": 60, "soft_time_limit": 45},
        },
    }
)

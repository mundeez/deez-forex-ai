from celery import Celery
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
    beat_schedule={
        "analyze-market-scalping": {
            "task": "app.tasks.analysis_tasks.run_full_analysis",
            "schedule": 300.0,  # Every 5 minutes for scalping/day trading
        },
        "check-open-positions": {
            "task": "app.tasks.execution_tasks.check_open_positions",
            "schedule": 60.0,  # Every minute for SL/TP + time-based exit
        },
        "auto-select-pairs": {
            "task": "app.tasks.analysis_tasks.auto_select_pairs",
            "schedule": 3600.0,
        },
        "update-daily-pnl": {
            "task": "app.tasks.execution_tasks.update_daily_pnl",
            "schedule": 3600.0,
        },
        "close-eod-positions": {
            "task": "app.tasks.execution_tasks.close_eod_positions",
            "schedule": {"hour": 21, "minute": 30, "day_of_week": "mon-fri"},
        },
        "close-weekend-positions": {
            "task": "app.tasks.execution_tasks.close_weekend_positions",
            "schedule": {"hour": 21, "minute": 0, "day_of_week": "fri"},
        },
    }
)

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
        "analyze-market-15m": {
            "task": "app.tasks.analysis_tasks.run_full_analysis",
            "schedule": 900.0,
        },
        "auto-select-pairs": {
            "task": "app.tasks.analysis_tasks.auto_select_pairs",
            "schedule": 3600.0,
        },
        "update-daily-pnl": {
            "task": "app.tasks.execution_tasks.update_daily_pnl",
            "schedule": 3600.0,
        },
    }
)

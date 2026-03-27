from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings


settings = get_settings()

celery_app = Celery(
    "market_reaction_forecaster",
    broker=settings.redis_url if settings.redis_url else "memory://",
    backend=settings.redis_url if settings.redis_url else "cache+memory://",
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager or settings.app_env == "test",
    task_ignore_result=False,
    timezone=settings.market_refresh_timezone,
    beat_schedule=(
        {
            "weekday-market-refresh": {
                "task": "market.refresh_state",
                "schedule": crontab(
                    minute=settings.market_refresh_minute_local,
                    hour=settings.market_refresh_hour_local,
                    day_of_week="1-5",
                ),
            }
        }
        if settings.worker_scheduler_enabled
        else {}
    ),
)

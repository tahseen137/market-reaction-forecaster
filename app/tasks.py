from __future__ import annotations

from app.celery_app import celery_app
from app.config import get_settings
from app.db import build_database_state
from app.services import refresh_market_state


@celery_app.task(name="market.refresh_state")
def refresh_market_state_task() -> dict[str, str]:
    settings = get_settings()
    database = build_database_state(settings)
    try:
        with database.session_factory() as session:
            refresh_market_state(session, settings)
        return {"status": "ok"}
    finally:
        database.engine.dispose()

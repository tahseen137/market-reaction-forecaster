from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActivityEvent, User


def _now() -> datetime:
    return datetime.now(UTC)


def list_activity_events(
    session: Session,
    limit: int = 50,
    *,
    actor_user_id: str | None = None,
    include_analytics: bool = False,
) -> list[ActivityEvent]:
    statement = select(ActivityEvent)
    if actor_user_id:
        statement = statement.where(ActivityEvent.actor_user_id == actor_user_id)
    if not include_analytics:
        statement = statement.where(~ActivityEvent.action.like("analytics.%"))
    statement = statement.order_by(ActivityEvent.created_at.desc()).limit(limit)
    return list(session.scalars(statement))


def record_activity(
    session: Session,
    *,
    action: str,
    entity_type: str,
    description: str,
    actor: User | None = None,
    actor_user: User | None = None,
    actor_username: str | None = None,
    entity_id: str | None = None,
    details: dict[str, object] | None = None,
) -> ActivityEvent:
    resolved_actor = actor_user or actor
    event = ActivityEvent(
        actor_user_id=resolved_actor.id if resolved_actor else None,
        actor_username=actor_username or (resolved_actor.username if resolved_actor else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        details=details or {},
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def record_analytics_event(
    session: Session,
    *,
    event_name: str,
    actor: User | None = None,
    actor_username: str | None = None,
    entity_type: str = "analytics",
    entity_id: str | None = None,
    details: dict[str, object] | None = None,
) -> ActivityEvent:
    return record_activity(
        session,
        action=f"analytics.{event_name}",
        actor=actor,
        actor_username=actor_username,
        entity_type=entity_type,
        entity_id=entity_id,
        description=f"Analytics event: {event_name}",
        details=details or {},
    )


def summarize_analytics_events(session: Session, *, lookback_days: int = 14) -> dict[str, object]:
    since = _now() - timedelta(days=lookback_days)
    rows = list(
        session.execute(
            select(ActivityEvent.action, func.count(ActivityEvent.id))
            .where(ActivityEvent.action.like("analytics.%"), ActivityEvent.created_at >= since)
            .group_by(ActivityEvent.action)
        )
    )
    counts = {str(action).removeprefix("analytics."): int(count) for action, count in rows}

    active_user_count = int(
        session.scalar(
            select(func.count(func.distinct(ActivityEvent.actor_user_id))).where(
                ActivityEvent.action.like("analytics.%"),
                ActivityEvent.created_at >= since,
                ActivityEvent.actor_user_id.is_not(None),
            )
        )
        or 0
    )
    return {
        "lookback_days": lookback_days,
        "counts": counts,
        "active_user_count": active_user_count,
    }

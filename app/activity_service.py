from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityEvent, User


def list_activity_events(session: Session, limit: int = 50) -> list[ActivityEvent]:
    statement = select(ActivityEvent).order_by(ActivityEvent.created_at.desc()).limit(limit)
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

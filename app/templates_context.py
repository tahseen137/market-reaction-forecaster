from __future__ import annotations

from typing import Any

from fastapi import Request

from app.config import Settings
from app.models import User


def page_context(
    *,
    request: Request,
    settings: Settings,
    user: User | None,
    page: str,
    title: str,
    body_class: str,
    session_status: Any,
    **data: Any,
) -> dict[str, Any]:
    return {
        "request": request,
        "settings": settings,
        "current_user": user,
        "current_page": page,
        "page_title": title,
        "body_class": body_class,
        "session_status": session_status,
        "page_data": data.pop("page_data", {}),
        **data,
    }

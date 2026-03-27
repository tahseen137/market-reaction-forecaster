from __future__ import annotations

from secrets import compare_digest
from urllib.parse import quote

from fastapi import Request

from app.models import User
from app.security import generate_csrf_token


SESSION_USER_ID_KEY = "user_id"
SESSION_USERNAME_KEY = "username"
SESSION_ROLE_KEY = "role"
SESSION_CSRF_KEY = "csrf_token"


def _has_session(request: Request) -> bool:
    return "session" in request.scope


def sanitize_next_path(next_path: str | None) -> str:
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    return next_path


def login_redirect(next_path: str | None = "/") -> str:
    return f"/login?next={quote(sanitize_next_path(next_path), safe='')}"


def auth_required(request: Request) -> bool:
    return bool(getattr(request.app.state, "auth_required", False))


def current_session_user_id(request: Request) -> str | None:
    if not _has_session(request):
        return None
    value = request.session.get(SESSION_USER_ID_KEY)
    return value if isinstance(value, str) and value else None


def current_csrf_token(request: Request) -> str | None:
    if not _has_session(request):
        return None
    value = request.session.get(SESSION_CSRF_KEY)
    return value if isinstance(value, str) and value else None


def ensure_csrf_token(request: Request) -> str:
    if not _has_session(request):
        return ""
    token = current_csrf_token(request)
    if token:
        return token
    token = generate_csrf_token()
    request.session[SESSION_CSRF_KEY] = token
    return token


def csrf_token_matches(request: Request, candidate: str | None) -> bool:
    expected = current_csrf_token(request)
    if not expected or not candidate:
        return False
    return compare_digest(expected, candidate)


def is_authenticated(request: Request, current_user: User | None = None) -> bool:
    if not auth_required(request):
        return True
    return current_user is not None and current_session_user_id(request) == current_user.id


def set_authenticated_user_session(request: Request, user: User) -> str:
    request.session.clear()
    request.session[SESSION_USER_ID_KEY] = user.id
    request.session[SESSION_USERNAME_KEY] = user.username
    request.session[SESSION_ROLE_KEY] = user.role
    return ensure_csrf_token(request)


def refresh_session_from_user(request: Request, user: User) -> str:
    request.session[SESSION_USER_ID_KEY] = user.id
    request.session[SESSION_USERNAME_KEY] = user.username
    request.session[SESSION_ROLE_KEY] = user.role
    return ensure_csrf_token(request)


def clear_session(request: Request) -> None:
    if _has_session(request):
        request.session.clear()

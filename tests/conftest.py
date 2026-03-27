from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.db import build_database_state, init_database
from app.main import create_app
from app.services import (
    default_profile_payload,
    rebuild_model_portfolio_for_user,
    rebuild_user_recommendations_for_user,
    seed_demo_content,
    seed_universe,
)
from app.user_service import acknowledge_disclosures, create_or_update_profile, ensure_bootstrap_admin, get_user_by_username


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        site_url="http://testserver",
        database_url=f"sqlite:///{(tmp_path / 'market-test.db').resolve()}",
        uploads_dir=tmp_path / "uploads",
        session_secret="test-session-secret",
        bootstrap_admin_username="admin",
        bootstrap_admin_password="pilot-password",
        bootstrap_admin_email="admin@example.com",
        auto_create_schema=True,
        celery_task_always_eager=True,
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(settings: Settings) -> Generator[Session, None, None]:
    database = build_database_state(settings)
    init_database(database, auto_create_schema=True)
    db_session = database.session_factory()
    admin_user = ensure_bootstrap_admin(db_session, settings)
    seed_universe(db_session)
    seed_demo_content(db_session, settings)
    if admin_user is not None:
        if admin_user.profile is None:
            create_or_update_profile(db_session, admin_user, default_profile_payload())
        if admin_user.disclosures_acknowledged_at is None:
            acknowledge_disclosures(db_session, admin_user)
        rebuild_user_recommendations_for_user(db_session, admin_user)
        rebuild_model_portfolio_for_user(db_session, admin_user)
    try:
        yield db_session
    finally:
        db_session.close()
        database.engine.dispose()


def login(client: TestClient, username: str = "admin", password: str = "pilot-password") -> dict[str, str]:
    response = client.post("/api/session/login", json={"username": username, "password": password, "next_path": "/dashboard"})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def signup(client: TestClient, username: str, email: str | None = None) -> tuple[dict[str, object], dict[str, str]]:
    response = client.post(
        "/api/session/signup",
        json={
            "username": username,
            "email": email or f"{username}@example.com",
            "full_name": f"{username.title()} User",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return payload, {"X-CSRF-Token": payload["csrf_token"]}


def acknowledge(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    response = client.post("/api/profile/acknowledge-disclosures", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return login(client)


@pytest.fixture
def admin_user(session: Session):
    return get_user_by_username(session, "admin")

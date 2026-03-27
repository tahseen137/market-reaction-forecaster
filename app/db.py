from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


@dataclass
class DatabaseState:
    engine: Engine
    session_factory: sessionmaker[Session]


def ensure_database_url_directory(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw_path = database_url.removeprefix("sqlite:///")
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


def build_database_state(settings: Settings) -> DatabaseState:
    database_url = settings.resolved_database_url
    ensure_database_url_directory(database_url)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return DatabaseState(engine=engine, session_factory=session_factory)


def init_database(database_state: DatabaseState, auto_create_schema: bool = True) -> None:
    if not auto_create_schema:
        return
    from app import models  # noqa: F401

    Base.metadata.create_all(database_state.engine)


def database_is_ready(database_state: DatabaseState) -> bool:
    try:
        with database_state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

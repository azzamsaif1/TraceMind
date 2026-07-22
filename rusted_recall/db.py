"""Database engine and session management (directive sections 8, 9).

PostgreSQL is the production database (docker-compose + managed PG in
deployment). SQLite is supported for local development and tests so the domain
logic is verifiable without a running server. UUID ids are stored as strings for
portability across both backends.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from rusted_recall.config import get_settings
from rusted_recall.models import Base

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def _normalise_url(url: str) -> str:
    # Allow bare "sqlite:///path.db" or the psycopg-flavoured postgres URL.
    return url


def get_engine():  # type: ignore[no-untyped-def]
    global _engine, _SessionLocal
    if _engine is None:
        url = _normalise_url(get_settings().database_url)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def create_all() -> None:
    """Create all tables. Alembic owns production schema; this is for dev/tests."""
    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test helper: drop cached engine so a new DATABASE_URL takes effect."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None

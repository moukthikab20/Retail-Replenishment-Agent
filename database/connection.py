"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL
from database.models import Base

_engine = None
_SessionLocal = None


def get_engine(database_url: str | None = None):
    global _engine, _SessionLocal
    url = database_url or DATABASE_URL
    if _engine is None or (database_url and database_url != str(_engine.url)):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        _SessionLocal = sessionmaker(
            bind=_engine,
            autoflush=False,
            autocommit=False,
            future=True,
            expire_on_commit=False,
        )
    return _engine


def init_db(database_url: str | None = None) -> None:
    """Create all tables if they do not exist (idempotent)."""
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session(database_url: str | None = None) -> Generator[Session, None, None]:
    get_engine(database_url)
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test helper to clear the cached engine."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None

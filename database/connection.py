"""SQLAlchemy engine and session helpers (SQLite + PostgreSQL)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL
from database.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_bound_url: str | None = None


def normalize_database_url(url: str) -> str:
    """
    Normalize DATABASE_URL for SQLAlchemy.

    - Render/Heroku often provide postgres:// — convert to postgresql+psycopg://
    - Accept postgresql:// and rewrite to the psycopg3 driver when no driver is set
    - Leave sqlite:/// unchanged for local development and tests
    """
    if not url:
        raise ValueError("DATABASE_URL is empty")

    if url.startswith("sqlite:"):
        return url

    # postgres://user:pass@host/db
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]

    if url.startswith("postgresql+psycopg2://"):
        # Prefer psycopg v3 driver name used in requirements
        return "postgresql+psycopg://" + url[len("postgresql+psycopg2://") :]

    return url


def is_sqlite_url(url: str) -> bool:
    return normalize_database_url(url).startswith("sqlite:")


def get_engine(database_url: str | None = None) -> Engine:
    global _engine, _SessionLocal, _bound_url
    raw = database_url or DATABASE_URL
    url = normalize_database_url(raw)

    if _engine is not None and _bound_url == url:
        return _engine

    if _engine is not None:
        _engine.dispose()

    if is_sqlite_url(url):
        connect_args = {"check_same_thread": False}
        _engine = create_engine(url, future=True, connect_args=connect_args)
    else:
        _engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )

    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=False,
    )
    _bound_url = url
    return _engine


def init_db(database_url: str | None = None) -> None:
    """Create all tables if they do not exist (idempotent; used by tests/local)."""
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
    global _engine, _SessionLocal, _bound_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _bound_url = None


def database_healthcheck(database_url: str | None = None) -> dict[str, str | bool]:
    """Lightweight connectivity check used by later health endpoints."""
    try:
        engine = get_engine(database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        dialect = engine.dialect.name
        return {"ok": True, "dialect": dialect, "url_scheme": urlparse(str(engine.url)).scheme}
    except Exception as exc:  # noqa: BLE001 - surfaced as health status
        return {"ok": False, "error": str(exc)}


def redact_database_url(url: str | None = None) -> str:
    """Return a safe, non-secret representation of DATABASE_URL for logs/UI."""
    raw = normalize_database_url(url or DATABASE_URL)
    parsed = urlparse(raw)
    if parsed.password:
        netloc = parsed.netloc.replace(f":{parsed.password}", ":***")
        return urlunparse(parsed._replace(netloc=netloc))
    return raw

"""Database-backed exclusive lock for replenishment batch execution."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from config import SCHEDULER_LOCK_TTL_MINUTES
from database.connection import get_session, init_db
from database.models import SchedulerLockRow

logger = logging.getLogger(__name__)

BATCH_LOCK_NAME = "replenishment_batch"
# Stable 64-bit key for PostgreSQL advisory locks ('REPLEN' hash space).
_PG_ADVISORY_KEY = 0x5245504C5F424154  # truncated conceptually; use two-int form
_PG_LOCK_CLASS = 0x5245504C  # 'REPL'
_PG_LOCK_OBJ = 0x42415443  # 'BATC'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl() -> timedelta:
    return timedelta(minutes=max(5, int(SCHEDULER_LOCK_TTL_MINUTES or 180)))


def _dialect_name(session) -> str:
    bind = session.get_bind()
    return (bind.dialect.name if bind is not None else "sqlite").lower()


def try_acquire_batch_lock(*, holder: str | None = None) -> dict[str, Any]:
    """
    Acquire exclusive batch execution lease.

    PostgreSQL: session-scoped advisory lock via a short dedicated connection
    is awkward with pooled sessions, so we use a lease row on all dialects and
    additionally take pg_try_advisory_xact_lock during the acquire transaction
    on Postgres to serialize concurrent acquirers.
    """
    init_db()
    lock_holder = holder or f"holder-{uuid.uuid4().hex[:10]}"
    now = _now()
    expires = now + _ttl()
    with get_session() as session:
        dialect = _dialect_name(session)
        if dialect == "postgresql":
            got = session.execute(
                text("SELECT pg_try_advisory_xact_lock(:c, :o)"),
                {"c": _PG_LOCK_CLASS, "o": _PG_LOCK_OBJ},
            ).scalar()
            if not got:
                return {"acquired": False, "holder": None, "reason": "advisory_busy"}

        row = session.get(SchedulerLockRow, BATCH_LOCK_NAME)
        if row is not None:
            exp = row.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                return {
                    "acquired": False,
                    "holder": row.holder,
                    "reason": "lease_held",
                    "expires_at": exp.isoformat(),
                }
            row.holder = lock_holder
            row.acquired_at = now
            row.expires_at = expires
        else:
            try:
                session.add(
                    SchedulerLockRow(
                        lock_name=BATCH_LOCK_NAME,
                        holder=lock_holder,
                        acquired_at=now,
                        expires_at=expires,
                    )
                )
                session.flush()
            except IntegrityError:
                # Concurrent acquirer won the unique lock_name insert.
                session.rollback()
                logger.info("scheduler lease race for %s", BATCH_LOCK_NAME)
                return {"acquired": False, "holder": None, "reason": "lease_race"}
        return {
            "acquired": True,
            "holder": lock_holder,
            "expires_at": expires.isoformat(),
        }


def release_batch_lock(*, holder: str | None = None) -> None:
    """Release lease if holder matches (or force-clear when holder is None)."""
    init_db()
    with get_session() as session:
        row = session.get(SchedulerLockRow, BATCH_LOCK_NAME)
        if row is None:
            return
        if holder is not None and row.holder != holder:
            return
        session.delete(row)


def force_clear_batch_lock() -> None:
    """Test helper — drop the lease unconditionally."""
    release_batch_lock(holder=None)

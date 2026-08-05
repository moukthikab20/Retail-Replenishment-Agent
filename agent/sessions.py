"""Persistent multi-turn follow-up sessions (SDK Session, DB-backed).

One session per (user_id, recommendation_id). Conversational memory only —
recommendations, reviews, approvals, POs, and audit rows are never stored or
deleted here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from agents.memory.session import SessionABC
from sqlalchemy import delete, select

from database.connection import get_session, init_db
from database.models import FollowUpSessionMessageRow

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "openai_api_key",
        "authorization",
        "password",
        "secret",
        "token",
        "access_code",
        "demo_access_code",
        "database_url",
    }
)


def follow_up_session_id(user_id: str, recommendation_id: str) -> str:
    """Stable session identifier: one conversation per user + recommendation."""
    uid = (user_id or "").strip() or "anonymous"
    rid = (recommendation_id or "").strip()
    if not rid:
        raise ValueError("recommendation_id is required for a follow-up session")
    return f"replenishment:{uid}:{rid}"


def get_follow_up_session(user_id: str, recommendation_id: str) -> "DatabaseFollowUpSession":
    """Return a durable Agents SDK Session for this user/recommendation pair."""
    init_db()
    session_key = follow_up_session_id(user_id, recommendation_id)
    return DatabaseFollowUpSession(
        session_id=session_key,
        user_id=(user_id or "").strip() or "anonymous",
        recommendation_id=recommendation_id.strip(),
    )


def clear_follow_up_session(user_id: str, recommendation_id: str) -> int:
    """
    Clear conversational memory only for this user/recommendation.

    Does not delete recommendation, review, approval, purchase order, or audit rows.
    Returns the number of conversation items removed.
    """
    init_db()
    session_key = follow_up_session_id(user_id, recommendation_id)
    with get_session() as db:
        result = db.execute(
            delete(FollowUpSessionMessageRow).where(
                FollowUpSessionMessageRow.session_key == session_key
            )
        )
        deleted = int(result.rowcount or 0)
    logger.info(
        "cleared_follow_up_session session_key=%s deleted_items=%s",
        session_key,
        deleted,
    )
    return deleted


def _sanitize_item(item: Any) -> Any:
    if isinstance(item, dict):
        cleaned: dict[str, Any] = {}
        for key, value in item.items():
            key_l = str(key).lower()
            if key_l in _SENSITIVE_KEYS or "api_key" in key_l or "password" in key_l:
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = _sanitize_item(value)
        return cleaned
    if isinstance(item, list):
        return [_sanitize_item(v) for v in item]
    return item


def _run_sync(coro: Any) -> Any:
    """Run async session methods from sync callers without nesting event loops."""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if in_loop:
        # Should not be common for clear/get helpers; prefer creating a task-less bridge.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()
    return asyncio.run(coro)


class DatabaseFollowUpSession(SessionABC):
    """SQLAlchemy-backed Session for Postgres and SQLite app databases."""

    def __init__(
        self,
        *,
        session_id: str,
        user_id: str,
        recommendation_id: str,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.recommendation_id = recommendation_id
        self.session_settings = None

    async def get_items(self, limit: int | None = None) -> list[Any]:
        with get_session() as db:
            stmt = (
                select(FollowUpSessionMessageRow)
                .where(FollowUpSessionMessageRow.session_key == self.session_id)
                .order_by(FollowUpSessionMessageRow.id.asc())
            )
            rows = list(db.scalars(stmt))
        if limit is not None and limit >= 0:
            rows = rows[-limit:] if limit else []
        items: list[Any] = []
        for row in rows:
            try:
                items.append(json.loads(row.item_json))
            except json.JSONDecodeError:
                logger.warning("Skipping corrupt follow-up session item id=%s", row.id)
        return items

    async def add_items(self, items: list[Any]) -> None:
        if not items:
            return
        now = datetime.now(timezone.utc)
        with get_session() as db:
            for item in items:
                sanitized = _sanitize_item(item)
                db.add(
                    FollowUpSessionMessageRow(
                        session_key=self.session_id,
                        user_id=self.user_id,
                        recommendation_id=self.recommendation_id,
                        item_json=json.dumps(sanitized, default=str),
                        created_at=now,
                    )
                )

    async def pop_item(self) -> Any | None:
        with get_session() as db:
            stmt = (
                select(FollowUpSessionMessageRow)
                .where(FollowUpSessionMessageRow.session_key == self.session_id)
                .order_by(FollowUpSessionMessageRow.id.desc())
                .limit(1)
            )
            row = db.scalars(stmt).first()
            if row is None:
                return None
            try:
                item = json.loads(row.item_json)
            except json.JSONDecodeError:
                item = None
            db.delete(row)
            return item

    async def clear_session(self) -> None:
        with get_session() as db:
            db.execute(
                delete(FollowUpSessionMessageRow).where(
                    FollowUpSessionMessageRow.session_key == self.session_id
                )
            )

"""Per-user rate limits for shared demo usage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config import MAX_AGENT_RUNS_PER_USER_PER_HOUR, RATE_LIMIT_WINDOW_MINUTES
from database.connection import get_session
from database.models import AuditEventRow, RecommendationRow
from services.errors import RateLimitError


def count_recent_agent_runs(user_id: str, *, window_minutes: int | None = None) -> int:
    minutes = window_minutes or RATE_LIMIT_WINDOW_MINUTES
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with get_session() as session:
        stmt = (
            select(func.count())
            .select_from(AuditEventRow)
            .where(
                AuditEventRow.event_type == "recommendation_generated",
                AuditEventRow.user_id == user_id,
                AuditEventRow.timestamp >= cutoff,
            )
        )
        return int(session.scalar(stmt) or 0)


def assert_within_agent_run_limit(user_id: str | None) -> None:
    """Raise RateLimitError when the user exceeds the shared-demo run budget."""
    if not user_id:
        return
    used = count_recent_agent_runs(user_id)
    if used >= MAX_AGENT_RUNS_PER_USER_PER_HOUR:
        raise RateLimitError(
            f"Demo rate limit reached: {MAX_AGENT_RUNS_PER_USER_PER_HOUR} agent "
            f"analyses per {RATE_LIMIT_WINDOW_MINUTES} minutes. Try again later."
        )


def remaining_agent_runs(user_id: str | None) -> int | None:
    if not user_id:
        return None
    used = count_recent_agent_runs(user_id)
    return max(0, MAX_AGENT_RUNS_PER_USER_PER_HOUR - used)


def count_recommendations_for_user(user_id: str) -> int:
    with get_session() as session:
        stmt = (
            select(func.count())
            .select_from(RecommendationRow)
            .where(RecommendationRow.user_id == user_id)
        )
        return int(session.scalar(stmt) or 0)

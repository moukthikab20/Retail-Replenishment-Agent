"""Cron / timezone helpers for scheduled replenishment (no embedded scheduler)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from config import (
    REPLENISHMENT_CRON,
    REPLENISHMENT_RUN_INTERVAL_HOURS,
    REPLENISHMENT_SCHEDULE_ENABLED,
    REPLENISHMENT_STALE_TOLERANCE_MINUTES,
    REPLENISHMENT_TIMEZONE,
)


def resolve_timezone(name: str | None = None) -> ZoneInfo:
    tz_name = (name or REPLENISHMENT_TIMEZONE or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _aware_now(tz: ZoneInfo, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(tz)


def current_schedule_bucket(
    *,
    cron: str | None = None,
    tz_name: str | None = None,
    now: datetime | None = None,
) -> datetime:
    """
    Start of the current schedule bucket in the configured timezone.

    Derived from the previous (or current-on-the-minute) cron occurrence —
    never from wall-clock seconds alone.
    """
    expression = (cron or REPLENISHMENT_CRON).strip()
    tz = resolve_timezone(tz_name)
    local_now = _aware_now(tz, now)
    itr = croniter(expression, local_now)
    # If we are exactly on a boundary, get_prev returns the previous fire;
    # prefer the occurrence at-or-before now that defines this bucket.
    prev = itr.get_prev(datetime)
    # When now is exactly a fire time, croniter's get_prev steps back one.
    # Re-check: if next after prev is still <= now, use that instead.
    itr2 = croniter(expression, prev)
    candidate = itr2.get_next(datetime)
    if candidate <= local_now:
        return candidate
    return prev


def next_scheduled_occurrence(
    *,
    cron: str | None = None,
    tz_name: str | None = None,
    now: datetime | None = None,
) -> datetime:
    """Next cron fire after `now` in the configured timezone (schedule-aligned)."""
    expression = (cron or REPLENISHMENT_CRON).strip()
    tz = resolve_timezone(tz_name)
    local_now = _aware_now(tz, now)
    return croniter(expression, local_now).get_next(datetime)


def invocation_key_for_bucket(bucket: datetime) -> str:
    """Deterministic scheduled invocation key for a cron bucket."""
    if bucket.tzinfo is None:
        bucket = bucket.replace(tzinfo=timezone.utc)
    # Normalize to second precision (drop subseconds).
    normalized = bucket.replace(microsecond=0)
    return f"scheduled:{normalized.isoformat()}"


def run_id_for_invocation_key(invocation_key: str) -> str:
    digest = hashlib.sha256(invocation_key.encode("utf-8")).hexdigest()[:12]
    return f"RUN-{digest}"


def format_schedule_display(
    *,
    cron: str | None = None,
    interval_hours: int | None = None,
) -> str:
    hours = interval_hours or REPLENISHMENT_RUN_INTERVAL_HOURS
    expression = cron or REPLENISHMENT_CRON
    if expression.strip() == f"0 */{hours} * * *" or expression.strip() == "0 */6 * * *":
        return f"Every {hours} hours"
    return f"Cron `{expression}`"


def schedule_config_snapshot() -> dict[str, Any]:
    return {
        "enabled": bool(REPLENISHMENT_SCHEDULE_ENABLED),
        "cron": REPLENISHMENT_CRON,
        "timezone": REPLENISHMENT_TIMEZONE,
        "interval_hours": max(1, int(REPLENISHMENT_RUN_INTERVAL_HOURS or 6)),
        "stale_tolerance_minutes": max(1, int(REPLENISHMENT_STALE_TOLERANCE_MINUTES or 90)),
        "schedule_display": format_schedule_display(),
        "entry_point": "python -m jobs.run_replenishment",
    }

"""Replenishment batch run triggers — manual (Admin) and scheduled (CLI/cron).

Streamlit pages only *read* status or call run_now on an explicit button click.
Scheduled execution is via `python -m jobs.run_replenishment` (or the script).

CONTROLLED ENTRY: trigger_replenishment_run / run_now / run_scheduled / retry_failed_run
LOW-LEVEL: batch_run_service.run_replenishment_batch (tests/internal only)
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Sequence

from config import (
    CRON_SECRET,
    REPLENISHMENT_SCHEDULE_ENABLED,
    REPLENISHMENT_STALE_TOLERANCE_MINUTES,
    SCHEDULER_ACTOR,
)
from database.connection import get_session, init_db
from repositories import audit_repository, run_repository
from services import auth_service, batch_run_service
from services.schedule_time import (
    current_schedule_bucket,
    format_schedule_display,
    invocation_key_for_bucket,
    next_scheduled_occurrence,
    run_id_for_invocation_key,
    schedule_config_snapshot,
)
from services.scheduler_lock import release_batch_lock, try_acquire_batch_lock

logger = logging.getLogger(__name__)

TriggerType = Literal["scheduled", "manual", "retry"]

_FAILED_STATUSES = frozenset({"failed", "completed_with_errors"})
_SUCCESS_STATUSES = frozenset({"completed", "completed_with_errors"})

# Scheduler audit events (additive; keep replenishment_run_* dual-write).
AUDIT_SCHEDULED_TRIGGERED = "scheduled_replenishment_triggered"
AUDIT_SCHEDULED_SKIPPED_DISABLED = "scheduled_replenishment_skipped_disabled"
AUDIT_SCHEDULED_SKIPPED_OVERLAP = "scheduled_replenishment_skipped_overlap"
AUDIT_SCHEDULED_SKIPPED_DUPLICATE = "scheduled_replenishment_skipped_duplicate"
AUDIT_SCHEDULED_COMPLETED = "scheduled_replenishment_completed"
AUDIT_SCHEDULED_FAILED = "scheduled_replenishment_failed"
AUDIT_RUN_TRIGGERED = "replenishment_run_triggered"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def verify_cron_secret(provided: str | None) -> bool:
    """
    Validate a machine cron secret.

    When CRON_SECRET is unset/empty (local default), any call is allowed.
    When set, the provided secret must match (constant-time compare).
    """
    expected = (CRON_SECRET or "").strip()
    if not expected:
        return True
    actual = (provided or "").strip()
    if not actual:
        return False
    return hmac.compare_digest(actual, expected)


def require_cron_secret(provided: str | None) -> None:
    if not verify_cron_secret(provided):
        raise auth_service.AuthError("Invalid or missing cron secret")


def get_schedule_config() -> dict[str, Any]:
    snap = schedule_config_snapshot()
    # Prefer live module flag so tests can monkeypatch enable/disable.
    enabled = bool(REPLENISHMENT_SCHEDULE_ENABLED)
    return {
        **snap,
        "enabled": enabled,
        "cron_secret_configured": bool((CRON_SECRET or "").strip()),
        "trigger_modes": ["manual", "scheduled", "retry"],
        "interval_hours": snap["interval_hours"],
        "timezone": snap["timezone"],
        "cron": snap["cron"],
        "entry_point": snap["entry_point"],
        "schedule_display": snap["schedule_display"],
        "stale_tolerance_minutes": snap["stale_tolerance_minutes"],
    }


def compute_next_run_at(
    *,
    last_completed_at: datetime | str | None = None,
    interval_hours: int | None = None,
    now: datetime | None = None,
) -> datetime:
    """
    Next expected scheduled occurrence from the cron expression.

    `last_completed_at` / `interval_hours` are retained for call-site compatibility
    but do not shift the schedule — delayed runs must not drift the cadence.
    """
    del last_completed_at, interval_hours  # unused by design (cron-aligned)
    return next_scheduled_occurrence(now=now)


def _run_summary(run) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "initiated_by": run.initiated_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "total_items": run.total_items,
        "scored_items": run.scored_items,
        "auto_released_items": run.auto_released_items,
        "review_items": run.review_items,
        "blocked_items": run.blocked_items,
        "failed_items": run.failed_items,
        "policy_version": run.policy_version,
        "error_summary": run.error_summary,
        "invocation_key": getattr(run, "invocation_key", None),
        "scheduled_for": (
            run.scheduled_for.isoformat()
            if getattr(run, "scheduled_for", None) is not None
            else None
        ),
    }


def format_run_timestamp(value: datetime | str | None) -> str:
    """Compact UTC display for top bar / admin (never a hardcoded demo stamp)."""
    dt = _parse_dt(value)
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def canonical_next_run_display(*, now: datetime | None = None) -> str:
    """
    Single formatting helper for the global header NEXT RUN value.

    Page body should prefer qualitative schedule copy and avoid repeating this stamp.
    """
    schedule = get_schedule_config()
    if not schedule.get("enabled"):
        return "Not scheduled"
    return format_run_timestamp(next_scheduled_occurrence(now=now))


def _write_audit(
    event: str,
    *,
    actor: str,
    actor_role: str | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    details: dict[str, Any] | None = None,
    authentication_source: str | None = None,
) -> None:
    # System / scheduler actors are never treated as human identity providers.
    source = authentication_source
    if source is None:
        lowered = (actor or "").strip().lower()
        if lowered in {"scheduler", "cron", "system", "agent", "policy_engine"} or "scheduler" in lowered:
            source = "system"
    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            event,
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            authentication_source=source,
            details=details or {},
        )


def get_scheduler_health(*, now: datetime | None = None) -> dict[str, Any]:
    """
    Scheduler health taxonomy: healthy | stale | failed | disabled.
    """
    init_db()
    current = now or _now()
    schedule = get_schedule_config()
    next_at = next_scheduled_occurrence(now=current)
    with get_session() as session:
        last_scheduled = run_repository.get_latest_scheduled_run(session)
        last_success = run_repository.get_latest_scheduled_run(
            session, successful_only=True
        )
        active = run_repository.get_active_run(session)

    last_scheduled_at = None
    if last_scheduled is not None:
        last_scheduled_at = (
            last_scheduled.completed_at
            or last_scheduled.started_at
            or last_scheduled.created_at
        )
    last_success_at = None
    if last_success is not None:
        last_success_at = (
            last_success.completed_at
            or last_success.started_at
            or last_success.created_at
        )

    base = {
        "enabled": bool(schedule["enabled"]),
        "last_scheduled_run": _run_summary(last_scheduled),
        "last_successful_run": _run_summary(last_success),
        "next_scheduled_run": next_at.isoformat(),
        "next_scheduled_run_display": format_run_timestamp(next_at),
        "expected_interval_hours": schedule["interval_hours"],
        "stale_tolerance_minutes": schedule["stale_tolerance_minutes"],
        "cron": schedule["cron"],
        "timezone": schedule["timezone"],
        "active_run": _run_summary(active),
    }

    if not schedule["enabled"]:
        return {
            **base,
            "status": "disabled",
            "message": "Scheduled replenishment is disabled.",
        }

    if last_scheduled is not None and last_scheduled.status == "failed":
        if last_success is None or (
            last_scheduled.created_at
            and last_success.created_at
            and last_scheduled.created_at >= last_success.created_at
        ):
            return {
                **base,
                "status": "failed",
                "message": (
                    f"Most recent scheduled run {last_scheduled.run_id} failed."
                ),
            }

    tolerance = timedelta(minutes=int(schedule["stale_tolerance_minutes"]))
    # Stale if we are past (previous expected fire + tolerance) without success.
    # Use: if last success is older than (now - interval - tolerance), stale.
    interval = timedelta(hours=int(schedule["interval_hours"]))
    stale_before = current - interval - tolerance
    success_anchor = _parse_dt(last_success_at)
    if success_anchor is None or success_anchor < stale_before:
        overdue = None
        if success_anchor is not None:
            overdue_td = current - (success_anchor + interval)
            overdue = max(0, int(overdue_td.total_seconds() // 60))
        return {
            **base,
            "status": "stale",
            "message": (
                "No successful scheduled run within the expected schedule window"
                + (f" (about {overdue} minutes overdue)." if overdue is not None else ".")
            ),
            "overdue_minutes": overdue,
        }

    return {
        **base,
        "status": "healthy",
        "message": (
            f"Last successful scheduled run "
            f"{(last_success.run_id if last_success else '—')}; "
            f"next at {format_run_timestamp(next_at)}."
        ),
    }


def get_run_trigger_status(*, lightweight: bool = False) -> dict[str, Any]:
    """Admin / top-bar read model: last run, next run, status. Never starts a batch."""
    init_db()
    with get_session() as session:
        active = run_repository.get_active_run(session)
        latest = run_repository.get_latest_run(session, terminal_only=True)
        any_latest = run_repository.get_latest_run(session, terminal_only=False)
    schedule = get_schedule_config()
    if lightweight:
        health = {"status": "healthy" if schedule["enabled"] else "disabled"}
        eligible_count = 0
    else:
        eligible = batch_run_service.list_eligible_store_sku_pairs()
        eligible_count = len(eligible)
        health = get_scheduler_health()

    display_run = active or latest or any_latest
    next_at = next_scheduled_occurrence()
    current_status = (
        active.status
        if active is not None
        else (latest.status if latest is not None else "idle")
    )
    skus_scored = 0
    if display_run is not None:
        skus_scored = int(display_run.scored_items or 0)

    if not schedule["enabled"]:
        next_display = "Not scheduled"
        due = False
    else:
        next_display = canonical_next_run_display()
        due = next_at <= _now() and active is None

    return {
        "active_run": _run_summary(active),
        "latest_run": _run_summary(latest),
        "last_run": _run_summary(latest or any_latest),
        "eligible_pair_count": eligible_count,
        "skus_scored": skus_scored,
        "current_status": current_status,
        "next_run_at": None if not schedule["enabled"] else next_at.isoformat(),
        "next_run_display": next_display,
        "last_run_display": format_run_timestamp(
            (latest.completed_at if latest else None)
            or (latest.started_at if latest else None)
            or (any_latest.started_at if any_latest else None)
        ),
        "next_run_due": due,
        "schedule": schedule,
        "scheduler_health": health,
        "can_start_new_run": active is None,
        "can_retry_failed": (
            active is None
            and latest is not None
            and (latest.status or "") in _FAILED_STATUSES
        ),
    }


def format_topbar_status_pill(status: dict[str, Any] | None = None) -> str:
    """
    Single business-language status line for the fixed top-bar capsule.

    Never surfaces idle/waiting/next-run/scheduler/current-status wording.
    """
    from services.schedule_time import resolve_timezone

    payload = status if status is not None else get_run_trigger_status()
    # Terminal-only latest = a completed analysis the business can cite.
    completed = payload.get("latest_run")
    if not completed:
        return "Monitoring inventory · First analysis in progress"

    stamp = completed.get("completed_at") or completed.get("started_at")
    local_dt = _parse_dt(stamp)
    if local_dt is None:
        return "Monitoring inventory · First analysis in progress"

    # Product copy uses Central Time (CT) for the operational pill.
    local_dt = local_dt.astimezone(resolve_timezone("America/Chicago"))
    time_ct = f"{local_dt.strftime('%H:%M')} CT"
    date_part = f"{local_dt.strftime('%A, %B')} {local_dt.day}"
    skus = int(completed.get("scored_items") or payload.get("skus_scored") or 0)
    return (
        f"Last agent run {time_ct} · {skus} SKUs scored · {date_part} · {time_ct}"
    )


def get_topbar_run_metrics() -> dict[str, Any]:
    """Lightweight read model for the fixed top bar (no batch side effects)."""
    status = get_run_trigger_status(lightweight=True)
    health = status.get("scheduler_health") or {}
    return {
        "last_agent_run": status.get("last_run_display") or "—",
        "skus_scored": status.get("skus_scored", 0),
        "next_run": status.get("next_run_display") or "—",
        "current_status": status.get("current_status") or "idle",
        "next_run_due": bool(status.get("next_run_due")),
        "run_id": (status.get("last_run") or {}).get("run_id"),
        "scheduler_health": health.get("status"),
        "schedule_enabled": bool((status.get("schedule") or {}).get("enabled")),
        "status_pill": format_topbar_status_pill(status),
    }


def _skipped(
    *,
    blocked_reason: str,
    message: str,
    actor: str,
    audit_event: str | None,
    details: dict[str, Any] | None = None,
    active_run: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if audit_event:
        try:
            _write_audit(
                audit_event,
                actor=actor,
                run_id=(run or {}).get("run_id") if run else None,
                details={
                    "blocked_reason": blocked_reason,
                    "trigger_type": "scheduled",
                    **(details or {}),
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to write skip audit %s", audit_event)
    return {
        "started": False,
        "blocked_reason": blocked_reason,
        "message": message,
        "active_run": active_run,
        "run": run,
        "harmless_skip": True,
    }


def trigger_replenishment_run(
    *,
    trigger_type: TriggerType = "manual",
    initiated_by: str = "system",
    actor_role: str | None = None,
    store_sku_pairs: Sequence[tuple[str, str]] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    resume_active: bool = False,
    cron_secret: str | None = None,
    require_admin_role: bool = True,
    scheduled_for: datetime | None = None,
    invocation_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Controlled entry point for replenishment batches.

    Applies schedule enable gate, time-bucket idempotency (scheduled),
    and DB-backed exclusive lock / active-run overlap protection.
    """
    if trigger_type not in {"scheduled", "manual", "retry"}:
        raise ValueError("trigger_type must be scheduled, manual, or retry")

    if require_admin_role:
        if actor_role is None:
            raise auth_service.AuthError("Actor role is required to trigger a batch run")
        auth_service.require_permission(
            actor_role,
            auth_service.can_trigger_batch_run(actor_role),
            "trigger a replenishment batch run",
        )
    else:
        require_cron_secret(cron_secret)

    actor = initiated_by or SCHEDULER_ACTOR
    current = now or _now()

    # --- Schedule disabled (scheduled path only) ---
    if trigger_type == "scheduled" and not REPLENISHMENT_SCHEDULE_ENABLED:
        return _skipped(
            blocked_reason="schedule_disabled",
            message="Scheduled replenishment is disabled.",
            actor=actor,
            audit_event=AUDIT_SCHEDULED_SKIPPED_DISABLED,
            details={"scheduled_for": None},
        )

    # --- Time-bucket idempotency for scheduled ---
    bucket: datetime | None = None
    inv_key = invocation_key
    sched_for = scheduled_for
    deterministic_run_id: str | None = None
    if trigger_type == "scheduled":
        bucket = scheduled_for or current_schedule_bucket(now=current)
        if bucket.tzinfo is None:
            bucket = bucket.replace(tzinfo=timezone.utc)
        inv_key = inv_key or invocation_key_for_bucket(bucket)
        sched_for = bucket.astimezone(timezone.utc)
        deterministic_run_id = run_id_for_invocation_key(inv_key)

        init_db()
        with get_session() as session:
            existing = run_repository.get_run_by_invocation_key(session, inv_key)
            if existing is None and deterministic_run_id:
                existing = run_repository.get_run(session, deterministic_run_id)
        if existing is not None:
            summary = _run_summary(existing)
            return _skipped(
                blocked_reason="duplicate_invocation",
                message=(
                    f"Scheduled bucket {inv_key} already has run {existing.run_id} "
                    f"(status={existing.status})."
                ),
                actor=actor,
                audit_event=AUDIT_SCHEDULED_SKIPPED_DUPLICATE,
                details={
                    "invocation_key": inv_key,
                    "scheduled_for": sched_for.isoformat() if sched_for else None,
                    "existing_status": existing.status,
                },
                run=summary,
            )

    # --- Exclusive lock + active-run check ---
    lock = try_acquire_batch_lock(holder=f"{trigger_type}:{actor}")
    if not lock.get("acquired"):
        init_db()
        with get_session() as session:
            active = run_repository.get_active_run(session)
        return _skipped(
            blocked_reason="active_run",
            message=(
                "A replenishment run is already in progress "
                f"({(active.run_id if active else 'locked')})."
            ),
            actor=actor,
            audit_event=(
                AUDIT_SCHEDULED_SKIPPED_OVERLAP
                if trigger_type == "scheduled"
                else None
            ),
            details={
                "invocation_key": inv_key,
                "lock_reason": lock.get("reason"),
            },
            active_run=_run_summary(active) if active else None,
        )

    lock_holder = lock.get("holder")
    try:
        init_db()
        # Re-check invocation key under the lock (closes check-then-act race).
        if trigger_type == "scheduled" and inv_key:
            with get_session() as session:
                existing = run_repository.get_run_by_invocation_key(session, inv_key)
                if existing is None and deterministic_run_id:
                    existing = run_repository.get_run(session, deterministic_run_id)
            if existing is not None:
                return _skipped(
                    blocked_reason="duplicate_invocation",
                    message=(
                        f"Scheduled bucket {inv_key} already has run {existing.run_id} "
                        f"(status={existing.status})."
                    ),
                    actor=actor,
                    audit_event=AUDIT_SCHEDULED_SKIPPED_DUPLICATE,
                    details={
                        "invocation_key": inv_key,
                        "scheduled_for": sched_for.isoformat() if sched_for else None,
                        "existing_status": existing.status,
                    },
                    run=_run_summary(existing),
                )

        with get_session() as session:
            active = run_repository.get_active_run(session)

        if active is not None and not resume_active:
            return _skipped(
                blocked_reason="active_run",
                message=(
                    f"A replenishment run is already in progress ({active.run_id}, "
                    f"status={active.status}). Wait for completion or resume it."
                ),
                actor=actor,
                audit_event=(
                    AUDIT_SCHEDULED_SKIPPED_OVERLAP
                    if trigger_type == "scheduled"
                    else None
                ),
                details={"invocation_key": inv_key},
                active_run=_run_summary(active),
            )

        run_id = (
            active.run_id
            if (active is not None and resume_active)
            else deterministic_run_id
        )
        effective_trigger: TriggerType = trigger_type
        if run_id is not None and trigger_type == "manual" and active is not None:
            effective_trigger = "retry"

        if trigger_type == "scheduled":
            _write_audit(
                AUDIT_SCHEDULED_TRIGGERED,
                actor=actor,
                actor_role=actor_role,
                details={
                    "trigger_type": effective_trigger,
                    "invocation_key": inv_key,
                    "scheduled_for": sched_for.isoformat() if sched_for else None,
                },
            )

        try:
            result = batch_run_service.run_replenishment_batch(
                store_sku_pairs,
                trigger_type=effective_trigger,
                initiated_by=initiated_by,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                invocation_key=inv_key if trigger_type == "scheduled" else None,
                scheduled_for=sched_for if trigger_type == "scheduled" else None,
            )
        except Exception as exc:
            if trigger_type == "scheduled":
                _write_audit(
                    AUDIT_SCHEDULED_FAILED,
                    actor=actor,
                    actor_role=actor_role,
                    details={
                        "trigger_type": effective_trigger,
                        "invocation_key": inv_key,
                        "scheduled_for": sched_for.isoformat() if sched_for else None,
                        "error": str(exc)[:500],
                    },
                )
            raise

        _write_audit(
            AUDIT_RUN_TRIGGERED,
            actor=initiated_by,
            actor_role=actor_role,
            run_id=result.get("run_id"),
            user_id=user_id,
            session_id=session_id,
            details={
                "trigger_type": effective_trigger,
                "resumed": bool(active is not None and resume_active),
                "status": result.get("status"),
                "total_items": result.get("total_items"),
                "require_admin_role": require_admin_role,
                "invocation_key": inv_key,
                "scheduled_for": sched_for.isoformat() if sched_for else None,
            },
        )

        status = result.get("status")
        if trigger_type == "scheduled":
            if status == "failed":
                _write_audit(
                    AUDIT_SCHEDULED_FAILED,
                    actor=actor,
                    run_id=result.get("run_id"),
                    details={
                        "invocation_key": inv_key,
                        "scheduled_for": sched_for.isoformat() if sched_for else None,
                        "status": status,
                        "counts": {
                            "total_items": result.get("total_items"),
                            "scored_items": result.get("scored_items"),
                            "failed_items": result.get("failed_items"),
                        },
                    },
                )
            else:
                _write_audit(
                    AUDIT_SCHEDULED_COMPLETED,
                    actor=actor,
                    run_id=result.get("run_id"),
                    details={
                        "invocation_key": inv_key,
                        "scheduled_for": sched_for.isoformat() if sched_for else None,
                        "status": status,
                        "started_at": result.get("started_at"),
                        "completed_at": result.get("completed_at"),
                        "counts": {
                            "total_items": result.get("total_items"),
                            "scored_items": result.get("scored_items"),
                            "auto_released_items": result.get("auto_released_items"),
                            "review_items": result.get("review_items"),
                            "blocked_items": result.get("blocked_items"),
                            "no_order_items": result.get("no_order_items"),
                            "failed_items": result.get("failed_items"),
                        },
                    },
                )

        return {
            "started": True,
            "blocked_reason": None,
            "message": "Replenishment run completed"
            if status
            in {
                "completed",
                "completed_with_errors",
                "failed",
            }
            else "Replenishment run started",
            "active_run": None,
            "harmless_skip": False,
            "run": {
                "run_id": result.get("run_id"),
                "status": result.get("status"),
                "trigger_type": result.get("trigger_type"),
                "initiated_by": result.get("initiated_by"),
                "started_at": result.get("started_at"),
                "completed_at": result.get("completed_at"),
                "total_items": result.get("total_items"),
                "scored_items": result.get("scored_items"),
                "auto_released_items": result.get("auto_released_items"),
                "review_items": result.get("review_items"),
                "blocked_items": result.get("blocked_items"),
                "failed_items": result.get("failed_items"),
                "policy_version": result.get("policy_version"),
                "idempotent_replay": result.get("idempotent_replay", False),
                "invocation_key": inv_key,
                "scheduled_for": sched_for.isoformat() if sched_for else None,
            },
            "result": result,
        }
    finally:
        release_batch_lock(holder=lock_holder)


def run_now(
    *,
    actor: str,
    actor_role: str,
    session_id: str | None = None,
    store_sku_pairs: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Administrator 'Run now' — full catalog unless pairs are provided."""
    return trigger_replenishment_run(
        trigger_type="manual",
        initiated_by=actor,
        actor_role=actor_role,
        store_sku_pairs=store_sku_pairs,
        user_id=actor,
        session_id=session_id,
        require_admin_role=True,
    )


def run_scheduled(
    *,
    initiated_by: str | None = None,
    cron_secret: str | None = None,
    store_sku_pairs: Sequence[tuple[str, str]] | None = None,
    resume_active: bool = False,
    scheduled_for: datetime | None = None,
    invocation_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Machine-triggered scheduled batch (CLI / Render cron)."""
    return trigger_replenishment_run(
        trigger_type="scheduled",
        initiated_by=initiated_by or SCHEDULER_ACTOR,
        store_sku_pairs=store_sku_pairs,
        resume_active=resume_active,
        cron_secret=cron_secret,
        require_admin_role=False,
        scheduled_for=scheduled_for,
        invocation_key=invocation_key,
        now=now,
    )


def retry_failed_run(
    *,
    actor: str,
    actor_role: str,
    run_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Retry after a failed / completed_with_errors run.

    Starts a *new* persisted run (trigger_type=retry). Does not mutate the
    prior terminal run row. Blocked while another run is active.
    """
    auth_service.require_permission(
        actor_role,
        auth_service.can_trigger_batch_run(actor_role),
        "retry a failed replenishment run",
    )
    init_db()
    with get_session() as session:
        active = run_repository.get_active_run(session)
        if active is not None:
            return {
                "started": False,
                "blocked_reason": "active_run",
                "message": (
                    f"Cannot retry while {active.run_id} is {active.status}."
                ),
                "active_run": _run_summary(active),
                "run": None,
                "harmless_skip": True,
            }
        if run_id:
            prior = run_repository.get_run(session, run_id)
        else:
            prior = run_repository.get_latest_run(session, terminal_only=True)
        if prior is None:
            raise ValueError("No prior run available to retry")
        if (prior.status or "") not in _FAILED_STATUSES:
            raise ValueError(
                f"Run {prior.run_id} status is {prior.status}; "
                "retry is only for failed or completed_with_errors"
            )

    return trigger_replenishment_run(
        trigger_type="retry",
        initiated_by=actor,
        actor_role=actor_role,
        user_id=actor,
        session_id=session_id,
        require_admin_role=True,
    )

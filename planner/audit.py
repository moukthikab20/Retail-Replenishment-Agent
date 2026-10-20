"""Planning audit / observability."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from planner.contracts import Plan, StepTransition

_lock = threading.Lock()
_events: list[dict[str, Any]] = []
_MAX = 1000

AUDIT_PLAN_CREATED = "plan_created"
AUDIT_PLAN_STEP_TRANSITION = "plan_step_transition"
AUDIT_PLAN_RESUMED = "plan_resumed"
AUDIT_PLAN_APPROVAL_WAIT = "plan_approval_wait"
AUDIT_PLAN_LLM = "plan_llm_execution"
AUDIT_PLAN_TOOL = "plan_tool_execution"


def reset_plan_audit() -> None:
    with _lock:
        _events.clear()


def list_plan_audits(*, limit: int = 100, plan_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        items = list(_events)
    if plan_id:
        items = [e for e in items if e.get("plan_id") == plan_id]
    return items[-max(1, limit) :]


def record_plan_event(
    event_type: str,
    *,
    plan_id: str,
    step_id: str | None = None,
    duration_ms: float | None = None,
    detail: dict[str, Any] | None = None,
    execution_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    entry = {
        "event_type": event_type,
        "plan_id": plan_id,
        "step_id": step_id,
        "duration_ms": duration_ms,
        "execution_id": execution_id,
        "detail": dict(detail or {}),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _events.append(entry)
        if len(_events) > _MAX:
            del _events[: len(_events) - _MAX]

    if persist:
        try:
            from config import MEMORY_AUDIT_PERSIST
            from database.connection import get_session, init_db
            from repositories import audit_repository

            if MEMORY_AUDIT_PERSIST:
                init_db()
                with get_session() as session:
                    audit_repository.write_audit_event(
                        session,
                        event_type,
                        actor="planning_engine",
                        actor_type="system",
                        run_id=execution_id,
                        details=entry,
                    )
        except Exception:  # noqa: BLE001
            pass
    return entry


def record_transition(
    transition: StepTransition,
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    return record_plan_event(
        AUDIT_PLAN_STEP_TRANSITION,
        plan_id=transition.plan_id,
        step_id=transition.step_id,
        duration_ms=transition.duration_ms,
        execution_id=execution_id,
        detail={
            "from_status": transition.from_status,
            "to_status": transition.to_status,
            "detail": transition.detail,
        },
    )


def timeline_for_plan(plan: Plan) -> list[dict[str, Any]]:
    """Build an execution timeline from audits + step metadata."""
    audits = list_plan_audits(plan_id=plan.plan_id, limit=200)
    timeline: list[dict[str, Any]] = []
    for ev in audits:
        timeline.append(
            {
                "timestamp": ev.get("recorded_at"),
                "label": ev.get("event_type"),
                "step_id": ev.get("step_id"),
                "detail": ev.get("detail"),
                "duration_ms": ev.get("duration_ms"),
            }
        )
    for step in plan.steps:
        if step.started_at or step.completed_at:
            timeline.append(
                {
                    "timestamp": (step.completed_at or step.started_at).isoformat()
                    if (step.completed_at or step.started_at)
                    else None,
                    "label": f"step:{step.status}",
                    "step_id": step.id,
                    "detail": {"type": str(step.type), "name": step.name},
                    "duration_ms": step.duration_ms,
                }
            )
    return timeline

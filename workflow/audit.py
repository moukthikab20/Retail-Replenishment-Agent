"""Workflow audit events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_WORKFLOW_CREATED = "workflow_created"
AUDIT_WORKFLOW_STARTED = "workflow_started"
AUDIT_WORKFLOW_STEP_STARTED = "workflow_step_started"
AUDIT_WORKFLOW_STEP_COMPLETED = "workflow_step_completed"
AUDIT_WORKFLOW_STEP_FAILED = "workflow_step_failed"
AUDIT_WORKFLOW_RETRY_SCHEDULED = "workflow_retry_scheduled"
AUDIT_WORKFLOW_WAITING = "workflow_waiting"
AUDIT_WORKFLOW_RESUMED = "workflow_resumed"
AUDIT_WORKFLOW_CANCELLED = "workflow_cancelled"
AUDIT_WORKFLOW_COMPENSATION_STARTED = "workflow_compensation_started"
AUDIT_WORKFLOW_COMPENSATION_COMPLETED = "workflow_compensation_completed"
AUDIT_WORKFLOW_COMPLETED = "workflow_completed"
AUDIT_WORKFLOW_FAILED = "workflow_failed"

_EVENTS: list[dict[str, Any]] = []


def reset_workflow_audit() -> None:
    _EVENTS.clear()


def list_workflow_audit_events() -> list[dict[str, Any]]:
    return list(_EVENTS)


def record_workflow_event(
    event_type: str,
    *,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    attempt: int | None = None,
    actor: str | None = None,
    tool: str | None = None,
    business_refs: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "event_type": event_type,
        "workflow_id": workflow_id,
        "execution_id": execution_id,
        "plan_id": plan_id,
        "step_id": step_id,
        "attempt": attempt,
        "actor": actor or "workflow_engine",
        "tool": tool,
        "business_refs": dict(business_refs or {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": dict(details or {}),
    }
    _EVENTS.append(payload)
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
                    actor=actor or "workflow_engine",
                    actor_type="system",
                    run_id=execution_id or workflow_id,
                    details={
                        "workflow_id": workflow_id,
                        "plan_id": plan_id,
                        "step_id": step_id,
                        "attempt": attempt,
                        "tool": tool,
                        "business_refs": business_refs,
                        **dict(details or {}),
                    },
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("workflow_audit_persist_skipped err=%s", exc)
    return payload

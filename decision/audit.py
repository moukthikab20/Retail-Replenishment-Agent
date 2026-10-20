"""Decision audit trail — in-process + optional DB persist."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_DECISION_STARTED = "decision_started"
AUDIT_CANDIDATE_GENERATED = "candidate_generated"
AUDIT_CANDIDATE_SCORED = "candidate_scored"
AUDIT_DECISION_SELECTED = "decision_selected"
AUDIT_DECISION_EXECUTED = "decision_executed"
AUDIT_DECISION_ESCALATED = "decision_escalated"
AUDIT_DECISION_FAILED = "decision_failed"

_EVENTS: list[dict[str, Any]] = []


def reset_decision_audit() -> None:
    _EVENTS.clear()


def list_decision_audit_events() -> list[dict[str, Any]]:
    return list(_EVENTS)


def record_decision_event(
    event_type: str,
    *,
    evaluation_id: str | None = None,
    execution_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "event_type": event_type,
        "evaluation_id": evaluation_id,
        "execution_id": execution_id,
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
                    actor="decision_engine",
                    actor_type="system",
                    run_id=execution_id or evaluation_id,
                    details={
                        "evaluation_id": evaluation_id,
                        **dict(details or {}),
                    },
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("decision_audit_persist_skipped err=%s", exc)
    return payload

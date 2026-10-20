"""Event bus audit trail."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

AUDIT_EVENT_PUBLISHED = "event_published"
AUDIT_EVENT_RECEIVED = "event_received"
AUDIT_EVENT_PROCESSED = "event_processed"
AUDIT_EVENT_RETRIED = "event_retried"
AUDIT_EVENT_DEAD_LETTER = "event_dead_letter"
AUDIT_EVENT_REPLAYED = "event_replayed"

_EVENTS: list[dict[str, Any]] = []


def reset_event_audit() -> None:
    _EVENTS.clear()


def list_event_audit() -> list[dict[str, Any]]:
    return list(_EVENTS)


def record_bus_event(
    event_type: str,
    *,
    event_id: str | None = None,
    domain_event_type: str | None = None,
    subscriber: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "event_type": event_type,
        "event_id": event_id,
        "domain_event_type": domain_event_type,
        "subscriber": subscriber,
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
                    actor="event_bus",
                    actor_type="system",
                    run_id=event_id,
                    details={
                        "domain_event_type": domain_event_type,
                        "subscriber": subscriber,
                        **dict(details or {}),
                    },
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("event_bus_audit_persist_skipped err=%s", exc)
    return payload

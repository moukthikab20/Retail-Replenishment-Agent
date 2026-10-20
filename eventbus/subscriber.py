"""Typed event subscribers — side effects only; business services stay authoritative."""

from __future__ import annotations

import logging
from typing import Any

from eventbus.contracts import EventEnvelope
from eventbus.events import EventType
from eventbus.registry import get_registry

logger = logging.getLogger(__name__)

# In-process side-effect stores for Agent Ops / tests (not business authority).
_MEMORY_EVENTS: list[dict[str, Any]] = []
_NOTIFICATIONS: list[dict[str, Any]] = []
_OPS_EVENTS: list[dict[str, Any]] = []
_WORKFLOW_SIGNALS: list[dict[str, Any]] = []
_ERP_SIGNALS: list[dict[str, Any]] = []


def reset_subscriber_state() -> None:
    _MEMORY_EVENTS.clear()
    _NOTIFICATIONS.clear()
    _OPS_EVENTS.clear()
    _WORKFLOW_SIGNALS.clear()
    _ERP_SIGNALS.clear()


def memory_events() -> list[dict[str, Any]]:
    return list(_MEMORY_EVENTS)


def notification_events() -> list[dict[str, Any]]:
    return list(_NOTIFICATIONS)


def ops_events() -> list[dict[str, Any]]:
    return list(_OPS_EVENTS)


def workflow_signals() -> list[dict[str, Any]]:
    return list(_WORKFLOW_SIGNALS)


def erp_signals() -> list[dict[str, Any]]:
    return list(_ERP_SIGNALS)


def _handle_memory(event: EventEnvelope) -> None:
    _MEMORY_EVENTS.append(
        {
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "payload": dict(event.payload),
            "event_id": event.event_id,
        }
    )
    # Optional: append to memory audit trail without mutating business tables.
    try:
        from memory.audit import record_retrieval_audit

        # Lightweight breadcrumb only — not a retrieval.
        if event.event_type in {
            EventType.RECOMMENDATION_CREATED,
            EventType.RECOMMENDATION_APPROVED,
            EventType.RECOMMENDATION_REJECTED,
            EventType.ERP_ACKNOWLEDGED,
            EventType.ERP_REJECTED,
            EventType.WORKFLOW_COMPLETED,
            EventType.HUMAN_APPROVED,
            EventType.HUMAN_REJECTED,
        }:
            record_retrieval_audit(
                execution_id=event.correlation_id,
                retrieval_source=f"eventbus:{event.event_type}",
                record_count=1,
                duration_ms=0.0,
                memory_types=["event_subscription"],
                details={
                    "aggregate_id": event.aggregate_id,
                    "event_id": event.event_id,
                },
                persist=False,
            )
    except Exception:  # noqa: BLE001
        pass


def _handle_notifications(event: EventEnvelope) -> None:
    if event.event_type in {
        EventType.NOTIFICATION_REQUESTED,
        EventType.HUMAN_APPROVED,
        EventType.HUMAN_REJECTED,
        EventType.ERP_REJECTED,
        EventType.WORKFLOW_FAILED,
    }:
        _NOTIFICATIONS.append(
            {
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "payload": dict(event.payload),
            }
        )


def _handle_agent_ops(event: EventEnvelope) -> None:
    _OPS_EVENTS.append(event.model_dump(mode="json"))
    if len(_OPS_EVENTS) > 200:
        del _OPS_EVENTS[:-200]


def _handle_audit(event: EventEnvelope) -> None:
    # Audit trail already recorded at publish/receive/process layers.
    logger.debug("audit_subscriber event=%s id=%s", event.event_type, event.event_id)


def _handle_health(event: EventEnvelope) -> None:
    # No-op heartbeat consumer — proves health subscriber is wired.
    logger.debug("health_subscriber saw %s", event.event_type)


def _handle_workflow(event: EventEnvelope) -> None:
    """
    Workflow resume signals from approval / ERP acknowledgement.
    Does not reimplement workflow engine — records resume requests for coordinator.
    """
    signal = {
        "event_type": event.event_type,
        "aggregate_id": event.aggregate_id,
        "correlation_id": event.correlation_id,
        "payload": dict(event.payload),
        "event_id": event.event_id,
    }
    if event.event_type in {
        EventType.ERP_ACKNOWLEDGED,
        EventType.ERP_REJECTED,
        EventType.HUMAN_APPROVED,
        EventType.HUMAN_REJECTED,
        EventType.APPROVAL_COMPLETED,
        EventType.WORKFLOW_RESUME_REQUESTED,
    }:
        signal["resume_requested"] = True
        # Prefer explicit execution/workflow ids from payload.
        signal["execution_id"] = event.payload.get("execution_id") or event.correlation_id
        signal["workflow_id"] = event.payload.get("workflow_id")
        _WORKFLOW_SIGNALS.append(signal)
        # Best-effort auto-resume coordinator (fail-soft).
        try:
            from eventbus.integration import maybe_resume_workflow_from_event

            maybe_resume_workflow_from_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow_resume_hook_skipped err=%s", exc)


def _handle_erp(event: EventEnvelope) -> None:
    if event.event_type.startswith("ERP") or event.event_type in {
        EventType.ERP_QUEUED,
        EventType.ERP_SUBMITTED,
        EventType.ERP_ACKNOWLEDGED,
        EventType.ERP_REJECTED,
    }:
        _ERP_SIGNALS.append(
            {
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "payload": dict(event.payload),
            }
        )


def register_default_subscribers() -> None:
    registry = get_registry()
    registry.register(
        "memory",
        [
            EventType.RECOMMENDATION_CREATED,
            EventType.RECOMMENDATION_APPROVED,
            EventType.RECOMMENDATION_REJECTED,
            EventType.ERP_QUEUED,
            EventType.ERP_SUBMITTED,
            EventType.ERP_ACKNOWLEDGED,
            EventType.ERP_REJECTED,
            EventType.WORKFLOW_STARTED,
            EventType.WORKFLOW_COMPLETED,
            EventType.WORKFLOW_FAILED,
            EventType.HUMAN_APPROVED,
            EventType.HUMAN_REJECTED,
            EventType.APPROVAL_COMPLETED,
        ],
        _handle_memory,
    )
    registry.register(
        "notifications",
        [
            EventType.NOTIFICATION_REQUESTED,
            EventType.HUMAN_APPROVED,
            EventType.HUMAN_REJECTED,
            EventType.ERP_REJECTED,
            EventType.WORKFLOW_FAILED,
        ],
        _handle_notifications,
    )
    registry.register("agent_ops", ["*"], _handle_agent_ops)
    registry.register("audit", ["*"], _handle_audit)
    registry.register("health", ["*"], _handle_health)
    registry.register(
        "workflow",
        [
            EventType.ERP_ACKNOWLEDGED,
            EventType.ERP_REJECTED,
            EventType.HUMAN_APPROVED,
            EventType.HUMAN_REJECTED,
            EventType.APPROVAL_COMPLETED,
            EventType.WORKFLOW_RESUME_REQUESTED,
            EventType.WORKFLOW_WAITING,
            EventType.WORKFLOW_STEP_COMPLETED,
        ],
        _handle_workflow,
    )
    registry.register(
        "erp",
        [
            EventType.ERP_QUEUED,
            EventType.ERP_SUBMITTED,
            EventType.ERP_ACKNOWLEDGED,
            EventType.ERP_REJECTED,
        ],
        _handle_erp,
    )

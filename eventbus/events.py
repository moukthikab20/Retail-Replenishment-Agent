"""Standard domain event type constants and builders."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from eventbus.contracts import EventEnvelope


class EventType:
    RECOMMENDATION_CREATED = "RecommendationCreated"
    RECOMMENDATION_APPROVED = "RecommendationApproved"
    RECOMMENDATION_REJECTED = "RecommendationRejected"
    WORKFLOW_STARTED = "WorkflowStarted"
    WORKFLOW_COMPLETED = "WorkflowCompleted"
    WORKFLOW_FAILED = "WorkflowFailed"
    WORKFLOW_PAUSED = "WorkflowPaused"
    WORKFLOW_RESUMED = "WorkflowResumed"
    WORKFLOW_STEP_COMPLETED = "WorkflowStepCompleted"
    WORKFLOW_WAITING = "WorkflowWaiting"
    WORKFLOW_RESUME_REQUESTED = "WorkflowResumeRequested"
    ERP_QUEUED = "ERPQueued"
    ERP_SUBMITTED = "ERPSubmitted"
    ERP_ACKNOWLEDGED = "ERPAcknowledged"
    ERP_REJECTED = "ERPRejected"
    INVENTORY_UPDATED = "InventoryUpdated"
    POLICY_CHANGED = "PolicyChanged"
    HUMAN_APPROVED = "HumanApproved"
    HUMAN_REJECTED = "HumanRejected"
    NOTIFICATION_REQUESTED = "NotificationRequested"
    APPROVAL_COMPLETED = "ApprovalCompleted"


STANDARD_EVENT_TYPES: tuple[str, ...] = (
    EventType.RECOMMENDATION_CREATED,
    EventType.RECOMMENDATION_APPROVED,
    EventType.RECOMMENDATION_REJECTED,
    EventType.WORKFLOW_STARTED,
    EventType.WORKFLOW_COMPLETED,
    EventType.WORKFLOW_FAILED,
    EventType.WORKFLOW_PAUSED,
    EventType.WORKFLOW_RESUMED,
    EventType.WORKFLOW_STEP_COMPLETED,
    EventType.WORKFLOW_WAITING,
    EventType.WORKFLOW_RESUME_REQUESTED,
    EventType.ERP_QUEUED,
    EventType.ERP_SUBMITTED,
    EventType.ERP_ACKNOWLEDGED,
    EventType.ERP_REJECTED,
    EventType.INVENTORY_UPDATED,
    EventType.POLICY_CHANGED,
    EventType.HUMAN_APPROVED,
    EventType.HUMAN_REJECTED,
    EventType.NOTIFICATION_REQUESTED,
    EventType.APPROVAL_COMPLETED,
)


def make_event(
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any] | None = None,
    actor: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    source: str = "retail-replenishment-poc",
    metadata: dict[str, Any] | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        correlation_id=correlation_id,
        causation_id=causation_id,
        timestamp=datetime.now(timezone.utc),
        source=source,
        actor=actor,
        payload=dict(payload or {}),
        metadata=dict(metadata or {}),
    )

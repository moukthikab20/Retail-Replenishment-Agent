"""Unified business audit trail — Checkpoint 11.

Events are append-only. Callers never update or delete prior rows.
Raw ``details_json`` is stored for technical expansion; UI summaries use labels.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import uuid4

from database.connection import get_session
from repositories import audit_repository

# Canonical Checkpoint 11 business event types (immutable contract for History filters).
BATCH_STARTED = "batch_started"
BATCH_COMPLETED = "batch_completed"
RECOMMENDATION_CREATED = "recommendation_created"
POLICY_EVALUATED = "policy_evaluated"
RECOMMENDATION_AUTO_RELEASED = "recommendation_auto_released"
RECOMMENDATION_BLOCKED = "recommendation_blocked"
RECOMMENDATION_OPENED = "recommendation_opened"
HUMAN_REVIEW_SUBMITTED = "human_review_submitted"
QUANTITY_ADJUSTED = "quantity_adjusted"
RECOMMENDATION_APPROVED = "recommendation_approved"
RECOMMENDATION_DECLINED = "recommendation_declined"
FORMAL_APPROVAL_REQUESTED = "formal_approval_requested"
FORMAL_APPROVAL_GRANTED = "formal_approval_granted"
FORMAL_APPROVAL_REJECTED = "formal_approval_rejected"
ORDER_QUEUED = "order_queued"
ERP_TRANSMISSION_STARTED = "erp_transmission_started"
ERP_TRANSMISSION_SUCCEEDED = "erp_transmission_succeeded"
ERP_TRANSMISSION_FAILED = "erp_transmission_failed"
PURCHASE_ORDER_CREATED = "purchase_order_created"
AGENT_FOLLOW_UP_QUESTION = "agent_follow_up_question"
SCENARIO_EVALUATED = "scenario_evaluated"

BUSINESS_EVENT_TYPES: tuple[str, ...] = (
    BATCH_STARTED,
    BATCH_COMPLETED,
    RECOMMENDATION_CREATED,
    POLICY_EVALUATED,
    RECOMMENDATION_AUTO_RELEASED,
    RECOMMENDATION_BLOCKED,
    RECOMMENDATION_OPENED,
    HUMAN_REVIEW_SUBMITTED,
    QUANTITY_ADJUSTED,
    RECOMMENDATION_APPROVED,
    RECOMMENDATION_DECLINED,
    FORMAL_APPROVAL_REQUESTED,
    FORMAL_APPROVAL_GRANTED,
    FORMAL_APPROVAL_REJECTED,
    ORDER_QUEUED,
    ERP_TRANSMISSION_STARTED,
    ERP_TRANSMISSION_SUCCEEDED,
    ERP_TRANSMISSION_FAILED,
    PURCHASE_ORDER_CREATED,
    AGENT_FOLLOW_UP_QUESTION,
    SCENARIO_EVALUATED,
)

# Events shown on Recommendation Detail (subset tied to one recommendation).
RECOMMENDATION_DETAIL_EVENT_TYPES: tuple[str, ...] = (
    RECOMMENDATION_CREATED,
    POLICY_EVALUATED,
    RECOMMENDATION_AUTO_RELEASED,
    RECOMMENDATION_BLOCKED,
    RECOMMENDATION_OPENED,
    HUMAN_REVIEW_SUBMITTED,
    QUANTITY_ADJUSTED,
    RECOMMENDATION_APPROVED,
    RECOMMENDATION_DECLINED,
    FORMAL_APPROVAL_REQUESTED,
    FORMAL_APPROVAL_GRANTED,
    FORMAL_APPROVAL_REJECTED,
    ORDER_QUEUED,
    ERP_TRANSMISSION_STARTED,
    ERP_TRANSMISSION_SUCCEEDED,
    ERP_TRANSMISSION_FAILED,
    PURCHASE_ORDER_CREATED,
    AGENT_FOLLOW_UP_QUESTION,
    SCENARIO_EVALUATED,
)

EVENT_LABELS: dict[str, str] = {
    BATCH_STARTED: "Batch started",
    BATCH_COMPLETED: "Batch completed",
    RECOMMENDATION_CREATED: "Recommendation created",
    POLICY_EVALUATED: "Policy evaluated",
    RECOMMENDATION_AUTO_RELEASED: "Recommendation auto-released",
    RECOMMENDATION_BLOCKED: "Recommendation blocked",
    RECOMMENDATION_OPENED: "Recommendation opened",
    HUMAN_REVIEW_SUBMITTED: "Human review submitted",
    QUANTITY_ADJUSTED: "Quantity adjusted",
    RECOMMENDATION_APPROVED: "Recommendation approved",
    RECOMMENDATION_DECLINED: "Recommendation declined",
    FORMAL_APPROVAL_REQUESTED: "Formal approval requested",
    FORMAL_APPROVAL_GRANTED: "Formal approval granted",
    FORMAL_APPROVAL_REJECTED: "Formal approval rejected",
    ORDER_QUEUED: "Order queued",
    ERP_TRANSMISSION_STARTED: "ERP transmission started",
    ERP_TRANSMISSION_SUCCEEDED: "ERP transmission succeeded",
    ERP_TRANSMISSION_FAILED: "ERP transmission failed",
    PURCHASE_ORDER_CREATED: "Purchase order created",
    AGENT_FOLLOW_UP_QUESTION: "Agent follow-up question",
    SCENARIO_EVALUATED: "Scenario evaluated",
}

ACTOR_TYPE_SYSTEM = "system"
ACTOR_TYPE_HUMAN = "human"
ACTOR_TYPE_AGENT = "agent"
ACTOR_TYPE_SCHEDULER = "scheduler"


def new_correlation_id() -> str:
    return f"COR-{uuid4().hex[:12]}"


def infer_actor_type(actor: str | None, *, actor_type: str | None = None) -> str:
    if actor_type:
        return actor_type
    value = (actor or "system").strip().lower()
    if value in {"system", "policy_engine", "erp_adapter", "mock_erp"}:
        return ACTOR_TYPE_SYSTEM
    if (
        value in {"scheduler", "cron", "job", "replenishment_scheduler", "render-cron"}
        or value.endswith("-cron")
        or "scheduler" in value
    ):
        return ACTOR_TYPE_SCHEDULER
    if value in {"agent", "assistant"} or value.startswith("agent"):
        return ACTOR_TYPE_AGENT
    if value in {"user", "reviewer", "approver"} or "@" in value:
        return ACTOR_TYPE_HUMAN
    if value.startswith("usr-") or value.startswith("user-"):
        return ACTOR_TYPE_HUMAN
    return ACTOR_TYPE_SYSTEM if value == "system" else ACTOR_TYPE_HUMAN


def record_event(
    event_type: str,
    *,
    actor: str = "system",
    actor_type: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    run_id: str | None = None,
    recommendation_id: str | None = None,
    review_id: str | None = None,
    approval_id: str | None = None,
    purchase_order_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    authentication_source: str | None = None,
    session=None,
) -> str:
    """Append a business audit event. Never overwrites prior events."""
    resolved_actor_type = infer_actor_type(actor, actor_type=actor_type)
    resolved_actor_id = actor_id or actor
    kwargs = {
        "event_type": event_type,
        "actor": actor,
        "actor_type": resolved_actor_type,
        "actor_id": resolved_actor_id,
        "actor_role": actor_role,
        "run_id": run_id,
        "recommendation_id": recommendation_id,
        "review_id": review_id,
        "approval_id": approval_id,
        "purchase_order_id": purchase_order_id,
        "store_id": store_id,
        "sku": sku,
        "correlation_id": correlation_id,
        "details": details,
        "user_id": user_id,
        "session_id": session_id,
        "authentication_source": authentication_source,
    }
    if session is not None:
        return audit_repository.write_audit_event(session, **kwargs)
    with get_session() as db:
        return audit_repository.write_audit_event(db, **kwargs)


def event_summary(event_type: str, details: dict[str, Any] | None = None) -> str:
    """Human-readable one-line summary without dumping raw JSON."""
    label = EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())
    details = details or {}
    bits: list[str] = [label]
    if event_type == QUANTITY_ADJUSTED:
        old_q = details.get("previous_quantity")
        new_q = details.get("new_quantity") or details.get("adjusted_quantity")
        if old_q is not None and new_q is not None:
            bits.append(f"{old_q} → {new_q}")
    elif event_type == POLICY_EVALUATED:
        disp = details.get("disposition")
        if disp:
            bits.append(f"disposition={disp}")
    elif event_type in {ERP_TRANSMISSION_FAILED, ERP_TRANSMISSION_SUCCEEDED}:
        po = details.get("purchase_order_id") or details.get("erp_reference")
        if po:
            bits.append(str(po))
    elif event_type == AGENT_FOLLOW_UP_QUESTION:
        q = details.get("question") or details.get("user_message")
        if q:
            bits.append(str(q)[:80])
    elif event_type == SCENARIO_EVALUATED:
        kind = details.get("scenario_type") or details.get("mode")
        if kind:
            bits.append(str(kind))
    store = details.get("store_id")
    sku = details.get("sku")
    if store and sku and event_type in {
        RECOMMENDATION_CREATED,
        POLICY_EVALUATED,
        RECOMMENDATION_AUTO_RELEASED,
        RECOMMENDATION_BLOCKED,
    }:
        bits.append(f"{store}/{sku}")
    return " · ".join(bits)


def _row_to_dict(row: Any, *, include_raw_details: bool = False) -> dict[str, Any]:
    try:
        details = json.loads(row.details_json or "{}")
    except json.JSONDecodeError:
        details = {}
    if not isinstance(details, dict):
        details = {"_raw": details}
    store_id = row.store_id or details.get("store_id")
    sku = row.sku or details.get("sku")
    payload = {
        "event_id": row.event_id,
        "event_type": row.event_type,
        "event_label": EVENT_LABELS.get(row.event_type, row.event_type),
        "summary": event_summary(row.event_type, details),
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "actor_type": row.actor_type or infer_actor_type(row.actor),
        "actor_id": row.actor_id or row.actor,
        "actor": row.actor,
        "actor_role": row.actor_role,
        "run_id": row.run_id,
        "recommendation_id": row.recommendation_id,
        "approval_id": row.approval_id,
        "purchase_order_id": row.purchase_order_id,
        "store_id": store_id,
        "sku": sku,
        "correlation_id": row.correlation_id,
        "review_id": row.review_id,
    }
    if include_raw_details:
        payload["details"] = details
        payload["details_json"] = row.details_json
    return payload


def list_business_events(
    *,
    date_from: date | datetime | None = None,
    date_to: date | datetime | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    recommendation_id: str | None = None,
    business_only: bool = True,
    include_raw_details: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    df = _as_datetime_start(date_from)
    dt = _as_datetime_end(date_to)
    with get_session() as session:
        rows = audit_repository.list_audit_events(
            session,
            recommendation_id=recommendation_id,
            run_id=run_id or None,
            event_type=event_type or None,
            event_types=list(BUSINESS_EVENT_TYPES) if business_only and not event_type else None,
            actor=actor or None,
            store_id=store_id or None,
            sku=sku or None,
            date_from=df,
            date_to=dt,
            limit=limit,
        )
        return [
            _row_to_dict(row, include_raw_details=include_raw_details) for row in rows
        ]


def list_recommendation_audit_trail(
    recommendation_id: str,
    *,
    include_raw_details: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with get_session() as session:
        rows = audit_repository.list_audit_events(
            session,
            recommendation_id=recommendation_id,
            event_types=list(RECOMMENDATION_DETAIL_EVENT_TYPES),
            limit=limit,
        )
        # Chronological for timeline (oldest first).
        rows = list(reversed(rows))
        return [
            _row_to_dict(row, include_raw_details=include_raw_details) for row in rows
        ]


def mark_recommendation_opened(
    recommendation_id: str,
    *,
    actor: str,
    actor_role: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str:
    return record_event(
        RECOMMENDATION_OPENED,
        actor=actor,
        actor_type=ACTOR_TYPE_HUMAN,
        actor_role=actor_role,
        recommendation_id=recommendation_id,
        store_id=store_id,
        sku=sku,
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        details={"recommendation_id": recommendation_id},
    )


def _as_datetime_start(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _as_datetime_end(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, time.max, tzinfo=timezone.utc)

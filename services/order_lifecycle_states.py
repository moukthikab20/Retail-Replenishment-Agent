"""Formal OrderIntent / PurchaseOrder ERP lifecycle state machine.

Canonical statuses (snake_case):
  queued_for_erp → transmitting → erp_acknowledged → completed
Failure / cancel branches:
  transmitting → transmission_failed → retry_pending → transmitting
  transmitting → erp_rejected (terminal)
  queued_for_erp → cancelled (terminal)

Legacy statuses from earlier checkpoints are normalized on read.
"""

from __future__ import annotations

from typing import Any

# Canonical lifecycle statuses
QUEUED_FOR_ERP = "queued_for_erp"
TRANSMITTING = "transmitting"
ERP_ACKNOWLEDGED = "erp_acknowledged"
COMPLETED = "completed"
TRANSMISSION_FAILED = "transmission_failed"
RETRY_PENDING = "retry_pending"
ERP_REJECTED = "erp_rejected"
CANCELLED = "cancelled"

# Backward-compatible aliases (still accepted on read / transition sources)
PENDING_ERP = "pending_erp"  # legacy queued
TRANSMITTED = "transmitted"  # legacy post-success (maps toward completed)
FAILED = "failed"  # legacy transmission_failed
ACKNOWLEDGED = "acknowledged"  # legacy erp_acknowledged
IN_TRANSIT = "in_transit"
RECEIVED = "received"

TERMINAL_SUCCESS = frozenset({COMPLETED, ERP_ACKNOWLEDGED, TRANSMITTED, IN_TRANSIT, RECEIVED})
TERMINAL_HARD = frozenset({CANCELLED, ERP_REJECTED})
ACKNOWLEDGED_OR_LATER = frozenset(
    {ERP_ACKNOWLEDGED, COMPLETED, TRANSMITTED, ACKNOWLEDGED, IN_TRANSIT, RECEIVED}
)

_LEGACY_TO_CANONICAL = {
    PENDING_ERP: QUEUED_FOR_ERP,
    FAILED: TRANSMISSION_FAILED,
    ACKNOWLEDGED: ERP_ACKNOWLEDGED,
    TRANSMITTED: COMPLETED,
    IN_TRANSIT: COMPLETED,
    RECEIVED: COMPLETED,
}

_ALLOWED: dict[str, frozenset[str]] = {
    QUEUED_FOR_ERP: frozenset({TRANSMITTING, CANCELLED}),
    TRANSMITTING: frozenset(
        {ERP_ACKNOWLEDGED, TRANSMISSION_FAILED, ERP_REJECTED, COMPLETED}
    ),
    ERP_ACKNOWLEDGED: frozenset({COMPLETED}),
    TRANSMISSION_FAILED: frozenset({RETRY_PENDING, TRANSMITTING}),
    RETRY_PENDING: frozenset({TRANSMITTING}),
    COMPLETED: frozenset(),
    ERP_REJECTED: frozenset(),
    CANCELLED: frozenset(),
}

_TRANSMISSION_STATUS = {
    QUEUED_FOR_ERP: "draft",
    TRANSMITTING: "queued",
    ERP_ACKNOWLEDGED: "sent",
    COMPLETED: "sent",
    TRANSMISSION_FAILED: "failed",
    RETRY_PENDING: "failed",
    ERP_REJECTED: "failed",
    CANCELLED: "draft",
}

# Customer-facing labels (internal status strings remain unchanged).
_LABELS = {
    QUEUED_FOR_ERP: "Ready to Send",
    PENDING_ERP: "Ready to Send",
    "draft": "Ready to Send",
    "queued": "Ready to Send",
    TRANSMITTING: "Sending",
    ERP_ACKNOWLEDGED: "Accepted by Purchasing System",
    ACKNOWLEDGED: "Accepted by Purchasing System",
    COMPLETED: "Completed",
    TRANSMITTED: "Completed",
    TRANSMISSION_FAILED: "Send Failed",
    FAILED: "Send Failed",
    RETRY_PENDING: "Retry Scheduled",
    ERP_REJECTED: "Rejected by Purchasing System",
    CANCELLED: "Cancelled",
    IN_TRANSIT: "Completed",
    RECEIVED: "Completed",
    "sent": "Completed",
}


class InvalidLifecycleTransition(ValueError):
    """Raised when an OrderIntent status transition is not allowed."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid order lifecycle transition: {current} → {target}"
        )


def normalize_status(status: str | None) -> str:
    """Map legacy status strings to the canonical lifecycle status."""
    raw = (status or QUEUED_FOR_ERP).strip().lower()
    return _LEGACY_TO_CANONICAL.get(raw, raw)


def assert_transition(current: str | None, target: str) -> str:
    """Validate and return the normalized target status."""
    from_status = normalize_status(current)
    to_status = normalize_status(target)
    if from_status == to_status:
        return to_status
    allowed = _ALLOWED.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidLifecycleTransition(from_status, to_status)
    return to_status


def can_transition(current: str | None, target: str) -> bool:
    try:
        assert_transition(current, target)
        return True
    except InvalidLifecycleTransition:
        return False


def is_terminal_success(status: str | None) -> bool:
    return normalize_status(status) in {COMPLETED, ERP_ACKNOWLEDGED}


def is_acknowledged_or_later(status: str | None) -> bool:
    return normalize_status(status) in {ERP_ACKNOWLEDGED, COMPLETED}


def can_cancel(status: str | None) -> bool:
    return normalize_status(status) == QUEUED_FOR_ERP


def can_manual_retry(status: str | None) -> bool:
    return normalize_status(status) in {TRANSMISSION_FAILED, RETRY_PENDING}


def can_transmit(status: str | None) -> bool:
    return normalize_status(status) in {
        QUEUED_FOR_ERP,
        RETRY_PENDING,
        TRANSMISSION_FAILED,
    }


def transmission_status_for(lifecycle: str | None) -> str:
    return _TRANSMISSION_STATUS.get(normalize_status(lifecycle), "draft")


def format_lifecycle_label(status: str | None) -> str:
    raw = (status or "").strip().lower()
    if raw in _LABELS:
        return _LABELS[raw]
    return _LABELS.get(normalize_status(raw), raw.replace("_", " ").title() or "—")


def transmission_idempotency_key(order_intent_id: str) -> str:
    return f"erp-order:{order_intent_id}"


def next_step_label(
    status: str | None,
    *,
    auto_transmit: bool = False,
) -> str:
    """Business next-step copy for Approved / Orders tables (UI only)."""
    canon = normalize_status(status)
    if canon == QUEUED_FOR_ERP:
        if auto_transmit:
            return "Scheduled to send"
        return "Requires manual send"
    if canon == TRANSMITTING:
        return "Sending to purchasing system"
    if canon in {ERP_ACKNOWLEDGED, COMPLETED}:
        return "Already transmitted"
    if canon == RETRY_PENDING:
        return "Retry scheduled"
    if canon == TRANSMISSION_FAILED:
        return "Send failed — retry available"
    if canon == ERP_REJECTED:
        return "Review required"
    if canon == CANCELLED:
        return "Cancelled"
    return format_lifecycle_label(canon)


def failure_guidance(
    status: str | None,
    *,
    last_failure: str | None = None,
    retry_at_display: str | None = None,
    business_rejection: bool | None = None,
) -> dict[str, Any]:
    """
    Customer-facing failure explanation.
    Distinguishes retryable technical failure vs purchasing rejection.
    """
    canon = normalize_status(status)
    reason = (last_failure or "").strip()
    rejected = canon == ERP_REJECTED or bool(business_rejection)
    if rejected:
        detail = reason or "The purchasing system rejected this order."
        return {
            "kind": "rejection",
            "title": "Purchasing system rejected this order",
            "message": f"Reason: {detail}. Review required.",
            "action_required": True,
            "will_retry": False,
        }
    if canon == RETRY_PENDING:
        when = retry_at_display or "the next retry window"
        return {
            "kind": "retry",
            "title": "Temporary connection problem",
            "message": (
                f"The agent will retry at {when}. No action is required."
            ),
            "action_required": False,
            "will_retry": True,
        }
    if canon == TRANSMISSION_FAILED:
        return {
            "kind": "failed",
            "title": "Send failed",
            "message": (
                (f"{reason}. " if reason else "")
                + "A retry may be scheduled, or an authorized user can retry."
            ).strip(),
            "action_required": True,
            "will_retry": True,
        }
    return {
        "kind": "none",
        "title": "",
        "message": "",
        "action_required": False,
        "will_retry": False,
    }


def status_summary(status: str | None) -> dict[str, Any]:
    canon = normalize_status(status)
    return {
        "status": canon,
        "label": format_lifecycle_label(canon),
        "transmission_status": transmission_status_for(canon),
        "can_cancel": can_cancel(canon),
        "can_retry": can_manual_retry(canon),
        "can_transmit": can_transmit(canon),
        "is_terminal_success": is_terminal_success(canon),
    }

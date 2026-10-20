"""Canonical agent execution lifecycle states and allowed transitions."""

from __future__ import annotations

from enum import StrEnum


class ExecutionStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_HUMAN = "waiting_for_human"
    RETRY_PENDING = "retry_pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Legacy HITL statuses kept for DB rows written before this engine.
    PAUSED = "paused"  # alias of waiting_for_human
    REJECTED = "rejected"  # terminal (sensitive tool declined)


TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.REJECTED,
    }
)

# Normalize legacy aliases before transition checks.
_STATUS_ALIASES: dict[str, ExecutionStatus] = {
    "paused": ExecutionStatus.WAITING_FOR_HUMAN,
    "rejected": ExecutionStatus.REJECTED,
}


def normalize_status(status: str | ExecutionStatus) -> ExecutionStatus:
    raw = str(status)
    if raw in _STATUS_ALIASES:
        return _STATUS_ALIASES[raw]
    return ExecutionStatus(raw)


ALLOWED_TRANSITIONS: dict[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.CREATED: frozenset(
        {
            ExecutionStatus.PLANNING,
            ExecutionStatus.RUNNING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.FAILED,
        }
    ),
    ExecutionStatus.PLANNING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }
    ),
    ExecutionStatus.RUNNING: frozenset(
        {
            ExecutionStatus.WAITING_FOR_TOOL,
            ExecutionStatus.WAITING_FOR_HUMAN,
            ExecutionStatus.RETRY_PENDING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }
    ),
    ExecutionStatus.WAITING_FOR_TOOL: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.RETRY_PENDING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }
    ),
    ExecutionStatus.WAITING_FOR_HUMAN: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.REJECTED,
        }
    ),
    ExecutionStatus.RETRY_PENDING: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        }
    ),
    ExecutionStatus.COMPLETED: frozenset(),
    ExecutionStatus.FAILED: frozenset(),
    ExecutionStatus.CANCELLED: frozenset(),
    ExecutionStatus.REJECTED: frozenset(),
    # Legacy paused rows behave like waiting_for_human.
    ExecutionStatus.PAUSED: frozenset(
        {
            ExecutionStatus.RUNNING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.WAITING_FOR_HUMAN,
        }
    ),
}


def can_transition(current: str | ExecutionStatus, target: str | ExecutionStatus) -> bool:
    cur = normalize_status(current)
    tgt = ExecutionStatus(str(target))
    # Allow no-op same-status for idempotent writes of waiting aliases.
    if cur == tgt:
        return True
    if cur == ExecutionStatus.PAUSED and tgt == ExecutionStatus.WAITING_FOR_HUMAN:
        return True
    if str(current) == "paused" and tgt == ExecutionStatus.WAITING_FOR_HUMAN:
        return True
    allowed = ALLOWED_TRANSITIONS.get(cur, frozenset())
    # Also allow from raw paused string mapped via normalize
    if str(current) == "paused":
        allowed = ALLOWED_TRANSITIONS[ExecutionStatus.WAITING_FOR_HUMAN] | frozenset(
            {ExecutionStatus.WAITING_FOR_HUMAN, ExecutionStatus.REJECTED}
        )
    return tgt in allowed


def assert_transition(current: str | ExecutionStatus, target: str | ExecutionStatus) -> None:
    if not can_transition(current, target):
        from services.errors import AppError

        raise AppError(
            f"Invalid execution transition: {current} → {target}",
            code="invalid_state_transition",
        )


# Audit event names for lifecycle (append-only; do not rewrite history).
AUDIT_EXECUTION_CREATED = "agent_execution_created"
AUDIT_EXECUTION_PLANNED = "agent_execution_planned"
AUDIT_EXECUTION_STARTED = "agent_execution_started"
AUDIT_TOOL_STARTED = "agent_tool_started"
AUDIT_TOOL_COMPLETED = "agent_tool_completed"
AUDIT_TOOL_FAILED = "agent_tool_failed"
AUDIT_RETRY_SCHEDULED = "agent_execution_retry_scheduled"
AUDIT_WAITING_FOR_HUMAN = "agent_waiting_for_human"
AUDIT_EXECUTION_RESUMED = "agent_execution_resumed"
AUDIT_EXECUTION_COMPLETED = "agent_execution_completed"
AUDIT_EXECUTION_FAILED = "agent_execution_failed"
AUDIT_EXECUTION_CANCELLED = "agent_execution_cancelled"

# Preserve existing HITL names.
AUDIT_TOOL_PAUSED = "tool_execution_paused"
AUDIT_TOOL_RESUMED = "tool_execution_resumed"
AUDIT_TOOL_REJECTED = "tool_execution_rejected"


class ExecutionType(StrEnum):
    RECOMMENDATION_ANALYSIS = "recommendation_analysis"
    FOLLOW_UP = "follow_up"
    SCENARIO_ANALYSIS = "scenario_analysis"
    ORDER_EXECUTION = "order_execution"

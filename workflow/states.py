"""Workflow state transition validation."""

from __future__ import annotations

from workflow.types import WorkflowStatus


ALLOWED_WORKFLOW_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.CREATED: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
        }
    ),
    WorkflowStatus.RUNNING: frozenset(
        {
            WorkflowStatus.WAITING_FOR_HUMAN,
            WorkflowStatus.WAITING_FOR_EXTERNAL,
            WorkflowStatus.RETRY_PENDING,
            WorkflowStatus.PAUSED,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.COMPLETED_WITH_ERRORS,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.COMPENSATING,
            WorkflowStatus.TIMED_OUT,
        }
    ),
    WorkflowStatus.WAITING_FOR_HUMAN: frozenset(
        {
            WorkflowStatus.RESUMING,
            WorkflowStatus.RUNNING,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
            WorkflowStatus.TIMED_OUT,
        }
    ),
    WorkflowStatus.WAITING_FOR_EXTERNAL: frozenset(
        {
            WorkflowStatus.RESUMING,
            WorkflowStatus.RUNNING,
            WorkflowStatus.RETRY_PENDING,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.FAILED,
            WorkflowStatus.TIMED_OUT,
        }
    ),
    WorkflowStatus.RETRY_PENDING: frozenset(
        {
            WorkflowStatus.RESUMING,
            WorkflowStatus.RUNNING,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.TIMED_OUT,
        }
    ),
    WorkflowStatus.PAUSED: frozenset(
        {
            WorkflowStatus.RESUMING,
            WorkflowStatus.RUNNING,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.RESUMING: frozenset(
        {
            WorkflowStatus.RUNNING,
            WorkflowStatus.WAITING_FOR_HUMAN,
            WorkflowStatus.WAITING_FOR_EXTERNAL,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.COMPENSATING: frozenset(
        {
            WorkflowStatus.COMPENSATED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }
    ),
    WorkflowStatus.COMPLETED: frozenset(),
    WorkflowStatus.COMPLETED_WITH_ERRORS: frozenset(),
    WorkflowStatus.FAILED: frozenset({WorkflowStatus.COMPENSATING}),
    WorkflowStatus.CANCELLED: frozenset({WorkflowStatus.COMPENSATING}),
    WorkflowStatus.COMPENSATED: frozenset(),
    WorkflowStatus.TIMED_OUT: frozenset({WorkflowStatus.COMPENSATING}),
}


class InvalidWorkflowTransition(ValueError):
    pass


def can_transition(current: str | WorkflowStatus, target: str | WorkflowStatus) -> bool:
    cur = WorkflowStatus(str(current))
    nxt = WorkflowStatus(str(target))
    if cur == nxt:
        return True
    return nxt in ALLOWED_WORKFLOW_TRANSITIONS.get(cur, frozenset())


def assert_transition(current: str | WorkflowStatus, target: str | WorkflowStatus) -> None:
    if not can_transition(current, target):
        raise InvalidWorkflowTransition(
            f"Invalid workflow transition: {current} -> {target}"
        )

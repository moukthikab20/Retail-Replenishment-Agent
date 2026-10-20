"""Workflow execution enums — extend planner concepts without replacing them."""

from __future__ import annotations

from enum import StrEnum


class WorkflowStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    WAITING_FOR_EXTERNAL = "waiting_for_external"
    RETRY_PENDING = "retry_pending"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    TIMED_OUT = "timed_out"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_PENDING = "retry_pending"
    WAITING = "waiting"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class FailureClass(StrEnum):
    TECHNICAL_RETRYABLE = "technical_retryable"
    TECHNICAL_NON_RETRYABLE = "technical_non_retryable"
    BUSINESS_REJECTION = "business_rejection"
    AUTHORIZATION_FAILURE = "authorization_failure"
    VALIDATION_FAILURE = "validation_failure"
    TIMEOUT = "timeout"
    DEPENDENCY_FAILURE = "dependency_failure"
    HUMAN_REQUIRED = "human_required"


class RetryMode(StrEnum):
    NONE = "none"
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    MANUAL = "manual"


class CompensationKind(StrEnum):
    NONE = "none"
    EXPLICIT = "explicit"
    NOT_SAFE = "not_safe"


TERMINAL_WORKFLOW = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.COMPLETED_WITH_ERRORS,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.COMPENSATED,
        WorkflowStatus.TIMED_OUT,
    }
)

SUCCEEDED_STEPS = frozenset(
    {
        WorkflowStepStatus.SUCCEEDED,
        WorkflowStepStatus.SKIPPED,
        WorkflowStepStatus.COMPENSATED,
    }
)

"""Workflow retry scheduling — respects business vs technical failure classes."""

from __future__ import annotations

from workflow.contracts import WorkflowRetryPolicy
from workflow.types import FailureClass, RetryMode


def should_retry(
    *,
    policy: WorkflowRetryPolicy,
    attempt: int,
    failure_class: str | FailureClass,
) -> bool:
    mode = str(policy.mode)
    if mode == RetryMode.NONE or mode == RetryMode.MANUAL:
        return False
    if attempt >= int(policy.max_attempts):
        return False
    cls = str(failure_class)
    if cls == FailureClass.BUSINESS_REJECTION:
        return False
    if cls == FailureClass.AUTHORIZATION_FAILURE:
        return False
    if cls == FailureClass.VALIDATION_FAILURE:
        return False
    if cls == FailureClass.HUMAN_REQUIRED:
        return False
    return cls in set(policy.retryable_classes)


def next_delay_seconds(policy: WorkflowRetryPolicy, attempt: int) -> float:
    base = max(0.0, float(policy.delay_seconds))
    if str(policy.mode) == RetryMode.EXPONENTIAL:
        return base * (float(policy.backoff_multiplier) ** max(0, attempt - 1))
    return base

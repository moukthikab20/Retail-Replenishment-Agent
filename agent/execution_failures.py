"""Failure classification for durable agent executions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FailureClass(StrEnum):
    MODEL_TIMEOUT = "model_timeout"
    TEMPORARY_PROVIDER_FAILURE = "temporary_provider_failure"
    TEMPORARY_NETWORK_FAILURE = "temporary_network_failure"
    SAFE_READ_TIMEOUT = "safe_read_timeout"
    AUTHORIZATION_DENIED = "authorization_denied"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    POLICY_PROHIBITED = "policy_prohibited"
    BUSINESS_RECORD_MISSING = "business_record_missing"
    NON_IDEMPOTENT_WRITE_UNCERTAIN = "non_idempotent_write_uncertain"
    CONCURRENCY_CONFLICT = "concurrency_conflict"
    UNKNOWN = "unknown"


RETRYABLE_CODES = frozenset(
    {
        FailureClass.MODEL_TIMEOUT,
        FailureClass.TEMPORARY_PROVIDER_FAILURE,
        FailureClass.TEMPORARY_NETWORK_FAILURE,
        FailureClass.SAFE_READ_TIMEOUT,
    }
)


@dataclass(frozen=True)
class ExecutionFailure:
    code: str
    message: str
    retryable: bool
    source: str = "execution"
    tool_name: str | None = None
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "source": self.source,
            "tool_name": self.tool_name,
            "attempt": self.attempt,
        }


def classify_failure(
    *,
    code: str | None = None,
    exc: BaseException | None = None,
    tool_name: str | None = None,
    attempt: int = 1,
    source: str = "execution",
) -> ExecutionFailure:
    """Map AppError codes / exception types to structured failures."""
    raw_code = (code or "").strip()
    message = ""
    if exc is not None:
        message = str(getattr(exc, "message", None) or exc)[:500]
        if not raw_code:
            raw_code = str(getattr(exc, "code", None) or type(exc).__name__)

    normalized = raw_code.lower().replace(" ", "_")

    mapping: dict[str, FailureClass] = {
        "authorization_denied": FailureClass.AUTHORIZATION_DENIED,
        "auth_denied": FailureClass.AUTHORIZATION_DENIED,
        "forbidden": FailureClass.AUTHORIZATION_DENIED,
        "invalid_tool_arguments": FailureClass.INVALID_TOOL_ARGUMENTS,
        "validation_error": FailureClass.INVALID_TOOL_ARGUMENTS,
        "invalid_state_transition": FailureClass.INVALID_STATE_TRANSITION,
        "hitl_not_paused": FailureClass.INVALID_STATE_TRANSITION,
        "policy_prohibited": FailureClass.POLICY_PROHIBITED,
        "business_record_missing": FailureClass.BUSINESS_RECORD_MISSING,
        "hitl_missing_run": FailureClass.BUSINESS_RECORD_MISSING,
        "recommendation_not_found": FailureClass.BUSINESS_RECORD_MISSING,
        "concurrency_conflict": FailureClass.CONCURRENCY_CONFLICT,
        "stale_execution_version": FailureClass.CONCURRENCY_CONFLICT,
        "model_timeout": FailureClass.MODEL_TIMEOUT,
        "timeout": FailureClass.MODEL_TIMEOUT,
        "temporary_provider_failure": FailureClass.TEMPORARY_PROVIDER_FAILURE,
        "rate_limit": FailureClass.TEMPORARY_PROVIDER_FAILURE,
        "temporary_network_failure": FailureClass.TEMPORARY_NETWORK_FAILURE,
        "connection_error": FailureClass.TEMPORARY_NETWORK_FAILURE,
        "safe_read_timeout": FailureClass.SAFE_READ_TIMEOUT,
        "non_idempotent_write_uncertain": FailureClass.NON_IDEMPOTENT_WRITE_UNCERTAIN,
    }

    klass = mapping.get(normalized, FailureClass.UNKNOWN)
    if klass == FailureClass.UNKNOWN:
        # Heuristics on exception type names
        name = type(exc).__name__.lower() if exc else ""
        if "timeout" in name or "timeout" in normalized:
            klass = FailureClass.MODEL_TIMEOUT
        elif "connection" in name or "network" in name:
            klass = FailureClass.TEMPORARY_NETWORK_FAILURE
        elif "rate" in name or "429" in normalized:
            klass = FailureClass.TEMPORARY_PROVIDER_FAILURE

    retryable = klass in RETRYABLE_CODES
    return ExecutionFailure(
        code=str(klass),
        message=message or raw_code or "Unknown execution failure",
        retryable=retryable,
        source=source,
        tool_name=tool_name,
        attempt=attempt,
    )

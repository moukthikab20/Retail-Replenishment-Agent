"""Failure classification — reuse service/tool error codes where available."""

from __future__ import annotations

from typing import Any

from workflow.types import FailureClass


def classify_failure(
    *,
    error: BaseException | None = None,
    error_code: str | None = None,
    message: str | None = None,
    business_rejection: bool = False,
    human_required: bool = False,
) -> tuple[FailureClass, bool]:
    """Return (failure_class, retryable). Business rejection is never auto-retried."""
    if human_required:
        return FailureClass.HUMAN_REQUIRED, False
    if business_rejection:
        return FailureClass.BUSINESS_REJECTION, False

    code = (error_code or "").strip().lower()
    text = (message or (str(error) if error else "")).lower()

    if code in {"authorization_denied", "forbidden", "unauthorized"} or "not authorized" in text:
        return FailureClass.AUTHORIZATION_FAILURE, False
    if code in {"validation_error", "invalid_tool_arguments", "policy_prohibited"}:
        return FailureClass.VALIDATION_FAILURE, False
    if code in {"business_rejection", "erp_rejected", "rejected"} or "business rejection" in text:
        return FailureClass.BUSINESS_REJECTION, False
    if code in {"timeout", "deadline_exceeded"} or "timeout" in text:
        return FailureClass.TIMEOUT, True
    if code in {
        "provider_unavailable",
        "temporary_failure",
        "connection_error",
        "retryable",
    } or "temporary" in text:
        return FailureClass.TECHNICAL_RETRYABLE, True
    if code in {"dependency_failure", "not_found"} or "dependency" in text:
        return FailureClass.DEPENDENCY_FAILURE, True
    if error is not None and type(error).__name__ in {"TimeoutError", "ConnectionError"}:
        return FailureClass.TECHNICAL_RETRYABLE, True
    return FailureClass.TECHNICAL_NON_RETRYABLE, False


def classify_from_step_output(output: dict[str, Any] | None) -> tuple[FailureClass, bool] | None:
    data = dict(output or {})
    if data.get("resolved") is False and data.get("waiting"):
        return FailureClass.HUMAN_REQUIRED, False
    if data.get("degraded") and data.get("error"):
        return classify_failure(error_code=str(data.get("error")), message=str(data.get("error")))
    if data.get("erp_rejected") or data.get("business_rejection"):
        return FailureClass.BUSINESS_REJECTION, False
    return None

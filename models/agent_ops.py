"""Typed contracts for Agent Operations monitoring (read-only views)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentExecutionSummary:
    execution_id: str
    execution_type: str | None
    status: str
    current_step: str | None
    next_action: str | None
    recommendation_id: str | None
    approval_id: str | None
    replenishment_run_id: str | None
    user_id: str | None
    session_id: str | None
    correlation_id: str | None
    attempt_count: int
    max_attempts: int
    waiting_reason: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: str | None
    updated_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    version: int = 1
    pending_tool_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentOperationsMetrics:
    active_executions: int
    waiting_for_human: int
    retry_pending: int
    failed_executions: int
    completed_today: int
    average_execution_duration_seconds: float | None
    open_hitl_requests: int
    tool_failure_rate: float | None = None
    timezone: str = "UTC"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolHistoryView:
    tool_call_id: str
    tool_name: str
    status: str
    attempt: int
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    retryable: bool
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelTurnView:
    turn_id: str
    model_name: str | None
    status: str
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

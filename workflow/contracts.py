"""Workflow contracts — adapt planner Plan/PlanStep where possible."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from workflow.types import (
    CompensationKind,
    FailureClass,
    RetryMode,
    WorkflowStatus,
    WorkflowStepStatus,
)


def new_workflow_id() -> str:
    return f"WF-{uuid4().hex[:12].upper()}"


def new_checkpoint_id() -> str:
    return f"CKP-{uuid4().hex[:10].upper()}"


class WorkflowRetryPolicy(BaseModel):
    mode: RetryMode | str = RetryMode.FIXED
    max_attempts: int = 3
    delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retryable_classes: list[str] = Field(
        default_factory=lambda: [
            FailureClass.TECHNICAL_RETRYABLE.value,
            FailureClass.TIMEOUT.value,
            FailureClass.DEPENDENCY_FAILURE.value,
        ]
    )


class WorkflowFailure(BaseModel):
    failure_class: FailureClass | str
    error_code: str | None = None
    error_message: str = ""
    retryable: bool = False
    step_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowCompensation(BaseModel):
    kind: CompensationKind | str = CompensationKind.NONE
    step_id: str | None = None
    compensatable: bool = False
    reason: str = ""
    service_action: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCancellation(BaseModel):
    workflow_id: str
    reason: str = ""
    actor: str | None = None
    actor_role: str | None = None
    run_compensation: bool = False
    cancelled_at: datetime | None = None


class WorkflowResumeRequest(BaseModel):
    workflow_id: str
    execution_id: str | None = None
    resolve_step_id: str | None = None
    actor: str | None = None
    actor_role: str | None = None
    approval_granted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepResult(BaseModel):
    step_id: str
    status: WorkflowStepStatus | str
    success: bool = False
    output_summary: dict[str, Any] = Field(default_factory=dict)
    business_refs: dict[str, Any] = Field(default_factory=dict)
    failure: WorkflowFailure | None = None
    attempt: int = 0
    duration_ms: float = 0.0
    tool_name: str | None = None
    tool_call_id: str | None = None


class ToolExecutionResult(BaseModel):
    tool_name: str
    tool_call_id: str
    status: str
    success: bool
    retryable: bool = False
    attempt: int = 1
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    output_summary: dict[str, Any] = Field(default_factory=dict)
    business_refs: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    failure_class: FailureClass | str | None = None


class WorkflowStepExecution(BaseModel):
    step_id: str
    plan_step_id: str
    step_type: str
    name: str = ""
    status: WorkflowStepStatus | str = WorkflowStepStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)
    attempt: int = 0
    max_attempts: int = 1
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    tool_name: str | None = None
    parallel_group: str | None = None
    output_summary: dict[str, Any] = Field(default_factory=dict)
    business_refs: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    failure_class: FailureClass | str | None = None
    replayable: bool = False
    compensation: WorkflowCompensation = Field(default_factory=WorkflowCompensation)
    idempotency_key: str | None = None


class WorkflowCheckpoint(BaseModel):
    checkpoint_id: str = Field(default_factory=new_checkpoint_id)
    workflow_id: str
    execution_id: str | None = None
    plan_id: str | None = None
    status: WorkflowStatus | str = WorkflowStatus.CREATED
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    waiting_steps: list[str] = Field(default_factory=list)
    step_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    retry_state: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowExecution(BaseModel):
    workflow_id: str = Field(default_factory=new_workflow_id)
    execution_id: str | None = None
    plan_id: str | None = None
    goal: str = ""
    workflow_type: str = "generic"
    status: WorkflowStatus | str = WorkflowStatus.CREATED
    steps: list[WorkflowStepExecution] = Field(default_factory=list)
    checkpoint: WorkflowCheckpoint | None = None
    retry_policy: WorkflowRetryPolicy = Field(default_factory=WorkflowRetryPolicy)
    decision_action: str | None = None
    require_human: bool = False
    business_refs: dict[str, Any] = Field(default_factory=dict)
    parallel_branches: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    version: int = 1
    degraded: bool = False
    degradation_reason: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_ops_summary(self) -> dict[str, Any]:
        ckp = self.checkpoint
        return {
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "status": str(self.status),
            "goal": self.goal,
            "workflow_type": self.workflow_type,
            "current_step": ckp.current_step if ckp else None,
            "completed_steps": list(ckp.completed_steps if ckp else []),
            "waiting_steps": list(ckp.waiting_steps if ckp else []),
            "failed_steps": list(ckp.failed_steps if ckp else []),
            "retries": dict(ckp.retry_state if ckp else {}),
            "parallel_branches": list(self.parallel_branches),
            "checkpoint": {
                "checkpoint_id": ckp.checkpoint_id if ckp else None,
                "version": ckp.version if ckp else self.version,
                "updated_at": ckp.updated_at.isoformat() if ckp and ckp.updated_at else None,
            },
            "resume_state": {
                "resumable": str(self.status)
                in {
                    WorkflowStatus.WAITING_FOR_HUMAN,
                    WorkflowStatus.WAITING_FOR_EXTERNAL,
                    WorkflowStatus.RETRY_PENDING,
                    WorkflowStatus.PAUSED,
                    WorkflowStatus.RUNNING,
                },
                "status": str(self.status),
                "current_step": ckp.current_step if ckp else None,
            },
            "duration_ms": round(self.duration_ms, 2),
            "decision_action": self.decision_action,
            "require_human": self.require_human,
            "business_refs": dict(self.business_refs),
            "steps": [
                {
                    "step_id": s.step_id,
                    "type": s.step_type,
                    "name": s.name,
                    "status": str(s.status),
                    "attempt": s.attempt,
                    "tool": s.tool_name,
                    "parallel_group": s.parallel_group,
                    "duration_ms": s.duration_ms,
                    "failure_class": s.failure_class,
                    "business_refs": s.business_refs,
                }
                for s in self.steps
            ],
            "timeline": list(self.events)[-40:],
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
        }


class WorkflowExecutionResult(BaseModel):
    workflow: WorkflowExecution
    success: bool
    terminal: bool
    waiting: bool = False
    failure: WorkflowFailure | None = None
    message: str = ""

"""Planning contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

from planner.types import ExecutionState, FailureAction, PlanStepStatus, PlanStepType


def new_plan_id() -> str:
    return f"PLAN-{uuid4().hex[:12]}"


def new_step_id(prefix: str = "step") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


class RetryPolicy(BaseModel):
    max_attempts: int = 1
    backoff_ms: int = 0
    on_failure: FailureAction = FailureAction.FAIL


class PlanStep(BaseModel):
    id: str
    type: PlanStepType
    name: str = ""
    dependencies: list[str] = Field(default_factory=list)
    status: PlanStepStatus = PlanStepStatus.PENDING
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: float = 30.0
    tool: str | None = None
    expected_output: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    attempt_count: int = 0
    branch: str | None = None
    parallel_group: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    error: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    rollback: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    plan_id: str = Field(default_factory=new_plan_id)
    goal: str
    objective: str = ""
    workflow: str = "generic"
    steps: list[PlanStep] = Field(default_factory=list)
    status: ExecutionState = ExecutionState.CREATED
    provider: str = "mock"
    max_depth: int = 16
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def step_map(self) -> dict[str, PlanStep]:
        return {s.id: s for s in self.steps}

    def to_ops_summary(self) -> dict[str, Any]:
        completed = [s.id for s in self.steps if s.status == PlanStepStatus.COMPLETED]
        blocked = [
            s.id
            for s in self.steps
            if s.status in {PlanStepStatus.BLOCKED, PlanStepStatus.WAITING, PlanStepStatus.FAILED}
        ]
        pending = [
            s.id
            for s in self.steps
            if s.status in {PlanStepStatus.PENDING, PlanStepStatus.READY, PlanStepStatus.RUNNING}
        ]
        current = next(
            (
                s.id
                for s in self.steps
                if s.status in {PlanStepStatus.RUNNING, PlanStepStatus.WAITING, PlanStepStatus.READY}
            ),
            pending[0] if pending else (completed[-1] if completed else None),
        )
        branches = sorted({s.parallel_group for s in self.steps if s.parallel_group})
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "workflow": self.workflow,
            "status": str(self.status),
            "provider": self.provider,
            "current_step": current,
            "completed_steps": completed,
            "blocked_steps": blocked,
            "pending_steps": pending,
            "parallel_branches": branches,
            "step_count": len(self.steps),
            "steps": [
                {
                    "id": s.id,
                    "type": str(s.type),
                    "name": s.name or s.id,
                    "status": str(s.status),
                    "dependencies": list(s.dependencies),
                    "tool": s.tool,
                    "parallel_group": s.parallel_group,
                    "duration_ms": s.duration_ms,
                    "attempt_count": s.attempt_count,
                }
                for s in self.steps
            ],
            "resume_state": {
                "resumable": self.status
                in {ExecutionState.WAITING, ExecutionState.BLOCKED, ExecutionState.RUNNING},
                "status": str(self.status),
                "current_step": current,
            },
        }


class TaskGraph(BaseModel):
    """DAG view of a plan — adjacency for dependency resolution."""

    plan_id: str
    nodes: dict[str, PlanStep] = Field(default_factory=dict)
    edges: dict[str, list[str]] = Field(default_factory=dict)  # step_id -> dependents

    @classmethod
    def from_plan(cls, plan: Plan) -> "TaskGraph":
        nodes = {s.id: s for s in plan.steps}
        edges: dict[str, list[str]] = {s.id: [] for s in plan.steps}
        for step in plan.steps:
            for dep in step.dependencies:
                edges.setdefault(dep, []).append(step.id)
        return cls(plan_id=plan.plan_id, nodes=nodes, edges=edges)


class ExecutionContext(BaseModel):
    execution_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    purchase_order_id: str | None = None
    workflow: str = "generic"
    goal: str = ""
    actor: str = "agent"
    actor_role: str | None = None
    memory_context: dict[str, Any] = Field(default_factory=dict)
    business_context: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionPolicy(BaseModel):
    max_parallel: int = 4
    max_depth: int = 16
    enable_parallel: bool = True
    default_timeout_seconds: float = 30.0
    default_retry: RetryPolicy = Field(default_factory=RetryPolicy)
    stop_on_failure: bool = True


class StepTransition(BaseModel):
    plan_id: str
    step_id: str
    from_status: str
    to_status: str
    duration_ms: float | None = None
    detail: str | None = None
    at: datetime | None = None


@runtime_checkable
class PlannerProvider(Protocol):
    provider_name: str

    def build_plan(self, context: ExecutionContext, *, policy: ExecutionPolicy) -> Plan:
        ...

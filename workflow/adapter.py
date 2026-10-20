"""Adapt planner Plan ↔ WorkflowExecution (reuse, don't duplicate graphs)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from planner.contracts import Plan
from planner.types import PlanStepStatus
from workflow.contracts import (
    WorkflowCheckpoint,
    WorkflowExecution,
    WorkflowRetryPolicy,
    WorkflowStepExecution,
    new_checkpoint_id,
    new_workflow_id,
)
from workflow.compensation import compensation_for_step
from workflow.sanitize import extract_business_refs, summarize_output
from workflow.types import WorkflowStatus, WorkflowStepStatus


_PLAN_TO_WF_STEP: dict[str, WorkflowStepStatus] = {
    str(PlanStepStatus.PENDING): WorkflowStepStatus.PENDING,
    str(PlanStepStatus.READY): WorkflowStepStatus.READY,
    str(PlanStepStatus.RUNNING): WorkflowStepStatus.RUNNING,
    str(PlanStepStatus.COMPLETED): WorkflowStepStatus.SUCCEEDED,
    str(PlanStepStatus.FAILED): WorkflowStepStatus.FAILED,
    str(PlanStepStatus.SKIPPED): WorkflowStepStatus.SKIPPED,
    str(PlanStepStatus.WAITING): WorkflowStepStatus.WAITING,
    str(PlanStepStatus.BLOCKED): WorkflowStepStatus.WAITING,
    str(PlanStepStatus.CANCELLED): WorkflowStepStatus.CANCELLED,
}


def plan_status_to_workflow(plan_status: str, *, has_errors: bool = False) -> WorkflowStatus:
    mapping = {
        "created": WorkflowStatus.CREATED,
        "running": WorkflowStatus.RUNNING,
        "waiting": WorkflowStatus.WAITING_FOR_HUMAN,
        "blocked": WorkflowStatus.PAUSED,
        "completed": WorkflowStatus.COMPLETED_WITH_ERRORS if has_errors else WorkflowStatus.COMPLETED,
        "failed": WorkflowStatus.FAILED,
        "cancelled": WorkflowStatus.CANCELLED,
    }
    return mapping.get(str(plan_status), WorkflowStatus.RUNNING)


def workflow_from_plan(
    plan: Plan,
    *,
    execution_id: str | None = None,
    workflow_id: str | None = None,
    decision_action: str | None = None,
    require_human: bool = False,
    business_refs: dict[str, Any] | None = None,
    retry_policy: WorkflowRetryPolicy | None = None,
) -> WorkflowExecution:
    now = datetime.now(timezone.utc)
    wf_id = workflow_id or new_workflow_id()
    steps: list[WorkflowStepExecution] = []
    for step in plan.steps:
        wf_step = WorkflowStepExecution(
            step_id=step.id,
            plan_step_id=step.id,
            step_type=str(step.type),
            name=step.name or step.id,
            status=_PLAN_TO_WF_STEP.get(str(step.status), WorkflowStepStatus.PENDING),
            dependencies=list(step.dependencies),
            attempt=int(step.attempt_count or 0),
            max_attempts=max(1, int(step.retry_policy.max_attempts or 1)),
            started_at=step.started_at,
            completed_at=step.completed_at,
            duration_ms=step.duration_ms,
            tool_name=step.tool,
            parallel_group=step.parallel_group,
            output_summary=summarize_output(step.output),
            business_refs=extract_business_refs(step.output, business_refs),
            error_message=step.error,
            replayable=bool((step.metadata or {}).get("replayable")),
            idempotency_key=(step.metadata or {}).get("idempotency_key")
            or f"{wf_id}:{step.id}",
        )
        wf_step.compensation = compensation_for_step(wf_step)
        steps.append(wf_step)

    completed = [s.step_id for s in steps if s.status == WorkflowStepStatus.SUCCEEDED]
    failed = [s.step_id for s in steps if s.status == WorkflowStepStatus.FAILED]
    waiting = [s.step_id for s in steps if s.status == WorkflowStepStatus.WAITING]
    current = next(
        (
            s.step_id
            for s in steps
            if s.status
            in {
                WorkflowStepStatus.RUNNING,
                WorkflowStepStatus.WAITING,
                WorkflowStepStatus.READY,
                WorkflowStepStatus.RETRY_PENDING,
            }
        ),
        None,
    )
    has_errors = bool(failed)
    status = plan_status_to_workflow(str(plan.status), has_errors=has_errors)
    ckp = WorkflowCheckpoint(
        checkpoint_id=new_checkpoint_id(),
        workflow_id=wf_id,
        execution_id=execution_id,
        plan_id=plan.plan_id,
        status=status,
        current_step=current,
        completed_steps=completed,
        failed_steps=failed,
        waiting_steps=waiting,
        step_outputs={s.step_id: s.output_summary for s in steps if s.output_summary},
        retry_state={},
        version=1,
        created_at=now,
        updated_at=now,
    )
    return WorkflowExecution(
        workflow_id=wf_id,
        execution_id=execution_id,
        plan_id=plan.plan_id,
        goal=plan.goal,
        workflow_type=plan.workflow,
        status=status,
        steps=steps,
        checkpoint=ckp,
        retry_policy=retry_policy or WorkflowRetryPolicy(),
        decision_action=decision_action,
        require_human=require_human,
        business_refs=dict(business_refs or {}),
        parallel_branches=sorted({s.parallel_group for s in steps if s.parallel_group}),
        started_at=now if status != WorkflowStatus.CREATED else None,
        version=1,
        metadata={"provider": plan.provider},
    )


def refresh_from_plan(workflow: WorkflowExecution, plan: Plan) -> WorkflowExecution:
    updated = workflow_from_plan(
        plan,
        execution_id=workflow.execution_id,
        workflow_id=workflow.workflow_id,
        decision_action=workflow.decision_action,
        require_human=workflow.require_human,
        business_refs=workflow.business_refs,
        retry_policy=workflow.retry_policy,
    )
    updated.events = list(workflow.events)
    updated.version = int(workflow.version) + 1
    if updated.checkpoint:
        updated.checkpoint.version = updated.version
        updated.checkpoint.retry_state = dict(
            (workflow.checkpoint.retry_state if workflow.checkpoint else {}) or {}
        )
    updated.degraded = workflow.degraded
    updated.degradation_reason = workflow.degradation_reason
    if workflow.started_at:
        updated.started_at = workflow.started_at
    return updated

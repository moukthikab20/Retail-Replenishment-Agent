"""Resume manager — continue plans after interruption / approval waits."""

from __future__ import annotations

from datetime import datetime, timezone

from planner.audit import AUDIT_PLAN_RESUMED, record_plan_event
from planner.contracts import ExecutionContext, ExecutionPolicy, Plan
from planner.executor import TaskExecutor
from planner.types import ExecutionState, PlanStepStatus, PlanStepType


class ResumeManager:
    """Skips completed steps and resumes from waiting / ready nodes."""

    def __init__(self, executor: TaskExecutor | None = None) -> None:
        self._executor = executor or TaskExecutor()

    def mark_step_resolved(self, plan: Plan, step_id: str, *, output: dict | None = None) -> Plan:
        step = plan.step_map().get(step_id)
        if step is None:
            raise KeyError(f"Unknown step: {step_id}")
        step.status = PlanStepStatus.COMPLETED
        step.output = {**(step.output or {}), **(output or {}), "resolved": True}
        step.completed_at = datetime.now(timezone.utc)
        plan.updated_at = datetime.now(timezone.utc)
        return plan

    def resume(
        self,
        plan: Plan,
        context: ExecutionContext,
        *,
        resolve_step_id: str | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> Plan:
        if policy is not None:
            self._executor.policy = policy

        if resolve_step_id:
            self.mark_step_resolved(plan, resolve_step_id)
            context.variables[f"resolve:{resolve_step_id}"] = True
            context.variables["resume_resolved"] = True

        # Skip already completed — leave status as-is.
        for step in plan.steps:
            if step.status == PlanStepStatus.RUNNING:
                step.status = PlanStepStatus.PENDING

        # Auto-resolve waiting human/approval if resume flag set for that step.
        for step in plan.steps:
            if step.status == PlanStepStatus.WAITING and step.type in {
                PlanStepType.APPROVAL,
                PlanStepType.HUMAN,
                PlanStepType.WAIT,
            }:
                if context.variables.get(f"resolve:{step.id}") or (
                    resolve_step_id is None and context.variables.get("resume_resolved")
                ):
                    self.mark_step_resolved(plan, step.id)

        record_plan_event(
            AUDIT_PLAN_RESUMED,
            plan_id=plan.plan_id,
            step_id=resolve_step_id,
            execution_id=context.execution_id,
            detail={"status_before": str(plan.status)},
        )
        plan.status = ExecutionState.RUNNING
        return self._executor.run(plan, context, stop_on_wait=True)

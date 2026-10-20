"""Planner façade — create / validate / execute / resume task graphs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from planner.audit import AUDIT_PLAN_CREATED, record_plan_event, timeline_for_plan
from planner.contracts import (
    ExecutionContext,
    ExecutionPolicy,
    Plan,
    PlannerProvider,
    TaskGraph,
)
from planner.dependencies import DependencyResolver
from planner.executor import TaskExecutor
from planner.resume import ResumeManager
from planner.types import ExecutionState
from planner.validator import PlanValidator


class Planner:
    """Planning Engine entry used by Agent Runtime."""

    def __init__(
        self,
        provider: PlannerProvider,
        *,
        policy: ExecutionPolicy | None = None,
        resolver: DependencyResolver | None = None,
        validator: PlanValidator | None = None,
        executor: TaskExecutor | None = None,
        resume_manager: ResumeManager | None = None,
    ) -> None:
        self._provider = provider
        self.policy = policy or ExecutionPolicy()
        self._resolver = resolver or DependencyResolver()
        self._validator = validator or PlanValidator(self._resolver)
        self._executor = executor or TaskExecutor(
            resolver=self._resolver, policy=self.policy
        )
        self._resume = resume_manager or ResumeManager(self._executor)

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "provider_name", "unknown")

    def create_plan(self, context: ExecutionContext) -> Plan:
        plan = self._provider.build_plan(context, policy=self.policy)
        self._validator.assert_valid(plan, policy=self.policy)
        plan.status = ExecutionState.CREATED
        plan.created_at = plan.created_at or datetime.now(timezone.utc)
        plan.updated_at = datetime.now(timezone.utc)
        record_plan_event(
            AUDIT_PLAN_CREATED,
            plan_id=plan.plan_id,
            execution_id=context.execution_id,
            detail={
                "workflow": plan.workflow,
                "step_count": len(plan.steps),
                "provider": plan.provider,
            },
        )
        return plan

    def task_graph(self, plan: Plan) -> TaskGraph:
        return self._resolver.graph(plan)

    def validate(self, plan: Plan) -> list[str]:
        return self._validator.validate(plan, policy=self.policy)

    def execute(
        self,
        plan: Plan,
        context: ExecutionContext,
        *,
        stop_on_wait: bool = True,
    ) -> Plan:
        self._executor.policy = self.policy
        return self._executor.run(plan, context, stop_on_wait=stop_on_wait)

    def resume(
        self,
        plan: Plan,
        context: ExecutionContext,
        *,
        resolve_step_id: str | None = None,
    ) -> Plan:
        return self._resume.resume(
            plan, context, resolve_step_id=resolve_step_id, policy=self.policy
        )

    def to_operational_plan(self, plan: Plan) -> dict[str, Any]:
        """Bridge to AgentExecutionEnvelope OperationalPlan shape."""
        return {
            "goal": plan.goal,
            "steps": [
                {
                    "step_id": s.id,
                    # Prefer tool name for envelope compatibility with legacy plans.
                    "action": s.tool or s.name or s.id,
                    "status": (
                        "completed"
                        if str(s.status) == "completed"
                        else "failed"
                        if str(s.status) == "failed"
                        else "skipped"
                        if str(s.status) == "skipped"
                        else "running"
                        if str(s.status) in {"running", "waiting"}
                        else "pending"
                    ),
                    "tool_name": s.tool,
                    "result_ref": s.output or None,
                }
                for s in plan.steps
            ],
        }

    def ops_bundle(self, plan: Plan) -> dict[str, Any]:
        summary = plan.to_ops_summary()
        summary["timeline"] = timeline_for_plan(plan)
        summary["task_graph"] = {
            "plan_id": plan.plan_id,
            "nodes": list(plan.step_map().keys()),
            "edges": TaskGraph.from_plan(plan).edges,
        }
        return summary

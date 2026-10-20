"""Plan validation."""

from __future__ import annotations

from planner.contracts import ExecutionPolicy, Plan
from planner.dependencies import DependencyResolver
from planner.types import PlanStepType


class PlanValidator:
    """Validates plan structure, depth, tools, and finish presence."""

    def __init__(self, resolver: DependencyResolver | None = None) -> None:
        self._resolver = resolver or DependencyResolver()

    def validate(self, plan: Plan, *, policy: ExecutionPolicy | None = None) -> list[str]:
        errors: list[str] = []
        policy = policy or ExecutionPolicy()
        if not plan.goal and not plan.objective:
            errors.append("missing_goal")
        if not plan.steps:
            errors.append("empty_plan")
        if len(plan.steps) > policy.max_depth:
            errors.append(f"max_depth_exceeded:{len(plan.steps)}>{policy.max_depth}")

        ids = [s.id for s in plan.steps]
        if len(ids) != len(set(ids)):
            errors.append("duplicate_step_ids")

        finish_steps = [s for s in plan.steps if s.type == PlanStepType.FINISH]
        if plan.steps and not finish_steps:
            errors.append("missing_finish_step")

        errors.extend(self._resolver.validate_acyclic(plan))

        # Tool steps must name a tool; LLM/approval/human/wait/finish do not require tools.
        for step in plan.steps:
            if step.type == PlanStepType.TOOL and not step.tool:
                errors.append(f"tool_step_missing_tool:{step.id}")
            if step.tool:
                try:
                    from llm.tools.registry import ToolRegistry

                    if not ToolRegistry().is_registered(step.tool):
                        # Soft: also accept agent.tool_registry names
                        from agent.tool_registry import get_tool_definition

                        if get_tool_definition(step.tool) is None:
                            errors.append(f"unknown_tool:{step.id}:{step.tool}")
                except Exception:  # noqa: BLE001
                    pass
        return errors

    def assert_valid(self, plan: Plan, *, policy: ExecutionPolicy | None = None) -> Plan:
        errors = self.validate(plan, policy=policy)
        if errors:
            raise ValueError(f"Invalid plan: {', '.join(errors)}")
        return plan

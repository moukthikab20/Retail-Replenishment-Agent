"""Dependency resolution for task graphs."""

from __future__ import annotations

from planner.contracts import Plan, PlanStep, TaskGraph
from planner.types import PlanStepStatus


class DependencyResolver:
    """Resolves ready steps, topological order, and cycle detection."""

    TERMINAL = frozenset(
        {
            PlanStepStatus.COMPLETED,
            PlanStepStatus.SKIPPED,
            PlanStepStatus.CANCELLED,
        }
    )

    def graph(self, plan: Plan) -> TaskGraph:
        return TaskGraph.from_plan(plan)

    def validate_acyclic(self, plan: Plan) -> list[str]:
        errors: list[str] = []
        nodes = plan.step_map()
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in nodes:
                    errors.append(f"missing_dependency:{step.id}->{dep}")
        # Kahn cycle check
        indeg = {s.id: 0 for s in plan.steps}
        for s in plan.steps:
            for dep in s.dependencies:
                if dep in indeg:
                    indeg[s.id] += 1
        queue = [sid for sid, d in indeg.items() if d == 0]
        seen = 0
        adj = {s.id: [] for s in plan.steps}
        for s in plan.steps:
            for dep in s.dependencies:
                if dep in adj:
                    adj[dep].append(s.id)
        while queue:
            cur = queue.pop()
            seen += 1
            for nxt in adj.get(cur, []):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if seen != len(plan.steps):
            errors.append("cycle_detected")
        return errors

    def topological_order(self, plan: Plan) -> list[str]:
        errors = self.validate_acyclic(plan)
        if errors:
            raise ValueError(";".join(errors))
        indeg = {s.id: 0 for s in plan.steps}
        adj = {s.id: [] for s in plan.steps}
        for s in plan.steps:
            for dep in s.dependencies:
                if dep in indeg:
                    indeg[s.id] += 1
                    adj[dep].append(s.id)
        queue = sorted(sid for sid, d in indeg.items() if d == 0)
        order: list[str] = []
        while queue:
            cur = queue.pop(0)
            order.append(cur)
            for nxt in sorted(adj.get(cur, [])):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        return order

    def dependencies_satisfied(self, plan: Plan, step: PlanStep) -> bool:
        nodes = plan.step_map()
        for dep in step.dependencies:
            parent = nodes.get(dep)
            if parent is None:
                return False
            if parent.status not in self.TERMINAL:
                return False
            if parent.status == PlanStepStatus.FAILED:
                return False
        return True

    def ready_steps(self, plan: Plan) -> list[PlanStep]:
        ready: list[PlanStep] = []
        for step in plan.steps:
            if step.status not in {PlanStepStatus.PENDING, PlanStepStatus.READY}:
                continue
            if self.dependencies_satisfied(plan, step):
                ready.append(step)
        return ready

    def group_parallel(self, steps: list[PlanStep]) -> list[list[PlanStep]]:
        """Fan-out: group ready steps by parallel_group (None = serial singleton)."""
        groups: dict[str, list[PlanStep]] = {}
        serial: list[list[PlanStep]] = []
        for step in steps:
            if step.parallel_group:
                groups.setdefault(step.parallel_group, []).append(step)
            else:
                serial.append([step])
        return serial + list(groups.values())

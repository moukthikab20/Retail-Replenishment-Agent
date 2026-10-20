"""Mock / rules planner providers — deterministic templates."""

from __future__ import annotations

from typing import Any

from planner.contracts import ExecutionContext, ExecutionPolicy, Plan
from planner.templates import build_template_plan


class MockPlannerProvider:
    """Deterministic template planner (default)."""

    provider_name = "mock"

    def build_plan(self, context: ExecutionContext, *, policy: ExecutionPolicy) -> Plan:
        return build_template_plan(context, policy=policy, provider_name=self.provider_name)

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_name,
            "message": "Mock planner ready (template graphs).",
        }


class RulesPlannerProvider:
    """Alias provider — same templates, distinct config key for fail-fast selection."""

    provider_name = "rules"

    def build_plan(self, context: ExecutionContext, *, policy: ExecutionPolicy) -> Plan:
        return build_template_plan(context, policy=policy, provider_name=self.provider_name)

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_name,
            "message": "Rules planner ready (template graphs).",
        }

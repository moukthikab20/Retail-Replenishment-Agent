"""Planner factory — PLANNER_PROVIDER selection with fail-fast."""

from __future__ import annotations

from typing import Any

from config import (
    PLANNER_ENABLE_PARALLEL,
    PLANNER_MAX_DEPTH,
    PLANNER_MAX_PARALLEL,
    PLANNER_PROVIDER,
)
from integrations.failures import ProviderConfigError
from planner.contracts import ExecutionPolicy
from planner.planner import Planner
from planner.providers.mock import MockPlannerProvider, RulesPlannerProvider

_SUPPORTED: dict[str, type] = {
    "mock": MockPlannerProvider,
    "rules": RulesPlannerProvider,
}

_planner: Planner | None = None


def validate_planner_provider_configuration() -> str:
    key = (PLANNER_PROVIDER or "mock").strip().lower()
    if key not in _SUPPORTED:
        available = ", ".join(sorted(_SUPPORTED))
        raise ProviderConfigError(
            f"Planner provider '{key}' is not available in this deployment. "
            f"Supported: {available}.",
            provider_key="planner",
        )
    return key


def default_execution_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        max_parallel=max(1, int(PLANNER_MAX_PARALLEL)),
        max_depth=max(1, int(PLANNER_MAX_DEPTH)),
        enable_parallel=bool(PLANNER_ENABLE_PARALLEL),
    )


def get_planner(*, force_new: bool = False) -> Planner:
    global _planner
    key = validate_planner_provider_configuration()
    if _planner is None or force_new:
        provider = _SUPPORTED[key]()
        _planner = Planner(provider, policy=default_execution_policy())
    return _planner


def reset_planner() -> None:
    global _planner
    _planner = None


def planner_health() -> dict[str, Any]:
    planner = get_planner()
    provider = getattr(planner, "_provider", None)
    payload = provider.health_check() if provider and hasattr(provider, "health_check") else {}
    payload.setdefault("ok", True)
    payload.setdefault("config", (PLANNER_PROVIDER or "mock").strip().lower())
    payload.setdefault(
        "policy",
        {
            "max_parallel": PLANNER_MAX_PARALLEL,
            "max_depth": PLANNER_MAX_DEPTH,
            "enable_parallel": PLANNER_ENABLE_PARALLEL,
        },
    )
    return payload

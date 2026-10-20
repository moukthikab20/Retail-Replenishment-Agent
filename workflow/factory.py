"""Workflow factory and health."""

from __future__ import annotations

from typing import Any

from workflow.engine import WorkflowEngine

_engine: WorkflowEngine | None = None


def get_workflow_engine(*, force_new: bool = False) -> WorkflowEngine:
    global _engine
    from config import (
        WORKFLOW_CHECKPOINTS_ENABLED,
        WORKFLOW_COMPENSATION_ENABLED,
        WORKFLOW_DEFAULT_TIMEOUT_SECONDS,
        WORKFLOW_MAX_PARALLEL,
        WORKFLOW_RETRY_LIMIT,
    )

    if _engine is None or force_new:
        _engine = WorkflowEngine(
            max_parallel=max(1, int(WORKFLOW_MAX_PARALLEL)),
            default_timeout_seconds=float(WORKFLOW_DEFAULT_TIMEOUT_SECONDS),
            retry_limit=max(1, int(WORKFLOW_RETRY_LIMIT)),
            checkpoints_enabled=bool(WORKFLOW_CHECKPOINTS_ENABLED),
            compensation_enabled=bool(WORKFLOW_COMPENSATION_ENABLED),
        )
    return _engine


def reset_workflow_engine() -> None:
    global _engine
    _engine = None


def workflow_health() -> dict[str, Any]:
    from config import (
        WORKFLOW_CHECKPOINTS_ENABLED,
        WORKFLOW_ENABLED,
        WORKFLOW_MAX_PARALLEL,
        WORKFLOW_RETRY_LIMIT,
    )

    try:
        engine = get_workflow_engine()
        return {
            "ok": True,
            "enabled": bool(WORKFLOW_ENABLED),
            "max_parallel": engine.max_parallel,
            "retry_limit": engine.retry_limit,
            "checkpoints_enabled": bool(WORKFLOW_CHECKPOINTS_ENABLED),
            "components": {
                "workflow_engine": "healthy" if WORKFLOW_ENABLED else "degraded",
                "workflow_checkpoint_store": (
                    "healthy" if WORKFLOW_CHECKPOINTS_ENABLED else "degraded"
                ),
                "workflow_executor": "healthy",
                "resume_engine": "healthy",
            },
            "message": "Workflow Execution Engine ready (reuses AgentRunStateRow checkpoints).",
            "persistence": "agent_run_states.state_json",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "enabled": bool(WORKFLOW_ENABLED),
            "error": type(exc).__name__,
            "components": {
                "workflow_engine": "unavailable",
                "workflow_checkpoint_store": "unavailable",
                "workflow_executor": "degraded",
                "resume_engine": "degraded",
            },
            "message": str(exc),
        }

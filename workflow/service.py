"""Workflow service façade — Agent Runtime coordination only."""

from __future__ import annotations

import logging
from typing import Any

from planner.contracts import Plan
from workflow.checkpoint import load_workflow_from_context, persist_workflow_to_context
from workflow.contracts import (
    WorkflowExecution,
    WorkflowExecutionResult,
    WorkflowResumeRequest,
)
from workflow.factory import get_workflow_engine, reset_workflow_engine, workflow_health

logger = logging.getLogger(__name__)


def attach_workflow_to_execution_context(
    context: dict[str, Any] | None,
    *,
    execution_id: str | None = None,
    goal: str | None = None,
    workflow_type: str | None = None,
    plan_snapshot: dict[str, Any] | None = None,
    decision_ops: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create workflow metadata from plan_snapshot (fail-soft).
    Does not execute mutating business steps at attach time.
    """
    base = dict(context or {})
    try:
        from config import WORKFLOW_ENABLED

        if not WORKFLOW_ENABLED:
            base["workflow_ops"] = {
                "status": "degraded",
                "degraded": True,
                "degradation_reason": "workflow_disabled",
            }
            return base

        snapshot = plan_snapshot or base.get("plan_snapshot")
        if not snapshot:
            base["workflow_ops"] = {
                "status": "created",
                "degraded": True,
                "degradation_reason": "no_plan_snapshot",
            }
            return base

        plan = Plan.model_validate(snapshot)
        decision = decision_ops or base.get("decision_ops") or {}
        engine = get_workflow_engine()
        wf = engine.create(
            plan,
            execution_id=execution_id,
            decision_action=decision.get("winning_action"),
            require_human=bool(decision.get("require_human")),
            business_refs={
                k: base.get(k)
                for k in (
                    "store_id",
                    "sku",
                    "recommendation_id",
                    "approval_id",
                    "order_intent_id",
                )
                if base.get(k)
            },
        )
        wf.goal = goal or wf.goal or plan.goal
        wf.workflow_type = workflow_type or wf.workflow_type or plan.workflow
        return persist_workflow_to_context(base, wf)
    except Exception as exc:  # noqa: BLE001
        logger.warning("workflow_attach_failed execution_id=%s err=%s", execution_id, exc)
        base["workflow_ops"] = {
            "status": "failed",
            "degraded": True,
            "degradation_reason": type(exc).__name__,
        }
        return base


def run_workflow_for_execution(
    *,
    execution_id: str,
    plan: Plan,
    goal: str,
    workflow_type: str,
    context: dict[str, Any] | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    business_context: dict[str, Any] | None = None,
    actor: str | None = None,
) -> tuple[WorkflowExecutionResult, dict[str, Any]]:
    """Execute workflow via planner TaskExecutor; persist checkpoint into context."""
    from config import WORKFLOW_ENABLED

    base = dict(context or {})
    if not WORKFLOW_ENABLED:
        # Fall through: caller may still run planner directly.
        return (
            WorkflowExecutionResult(
                workflow=WorkflowExecution(
                    execution_id=execution_id,
                    status="failed",
                    degraded=True,
                    degradation_reason="workflow_disabled",
                ),
                success=False,
                terminal=True,
                message="Workflow disabled",
            ),
            base,
        )

    engine = get_workflow_engine()
    decision = base.get("decision_ops") or {}
    # Decision is advisory — do not auto-mutate from DecisionOutcome.
    if decision.get("require_human") and decision.get("winning_action") in {
        "create_purchase_order",
        "split_order",
        "change_supplier",
        "transfer_inventory",
    }:
        # Still allow plan execution for analysis/tools; mutation gated by business services.
        pass

    wf = engine.create(
        plan,
        execution_id=execution_id,
        decision_action=decision.get("winning_action"),
        require_human=bool(decision.get("require_human")),
        business_refs={
            k: base.get(k)
            for k in ("store_id", "sku", "recommendation_id", "approval_id")
            if base.get(k)
        },
    )
    # Preserve prior workflow_id if present for continuity across resume.
    prior = load_workflow_from_context(base)
    if prior and prior.get("workflow_id"):
        wf.workflow_id = str(prior["workflow_id"])
        if wf.checkpoint:
            wf.checkpoint.workflow_id = wf.workflow_id

    result = engine.run(
        wf,
        plan,
        goal=goal,
        workflow_type=workflow_type,
        store_id=store_id,
        sku=sku,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        business_context=business_context,
        actor=actor,
    )
    base = persist_workflow_to_context(base, result.workflow)
    base["plan_snapshot"] = plan.model_dump(mode="json")
    return result, base


def resume_workflow_for_execution(
    *,
    execution_id: str,
    plan: Plan,
    goal: str,
    workflow_type: str,
    resolve_step_id: str | None = None,
    context: dict[str, Any] | None = None,
    actor: str | None = None,
    approval_granted: bool = False,
    store_id: str | None = None,
    sku: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
) -> tuple[WorkflowExecutionResult, dict[str, Any]]:
    base = dict(context or {})
    engine = get_workflow_engine()
    prior = load_workflow_from_context(base) or {}
    wf = engine.create(
        plan,
        execution_id=execution_id,
        decision_action=prior.get("decision_action"),
        require_human=bool(prior.get("require_human")),
    )
    if prior.get("workflow_id"):
        wf.workflow_id = str(prior["workflow_id"])
    from workflow.types import WorkflowStatus

    # Restore waiting status so resume transition is valid.
    if prior.get("status") in {
        WorkflowStatus.WAITING_FOR_HUMAN,
        WorkflowStatus.RETRY_PENDING,
        WorkflowStatus.PAUSED,
        WorkflowStatus.WAITING_FOR_EXTERNAL,
    }:
        wf.status = WorkflowStatus(str(prior["status"]))
    else:
        wf.status = WorkflowStatus.WAITING_FOR_HUMAN

    result = engine.resume(
        wf,
        plan,
        WorkflowResumeRequest(
            workflow_id=wf.workflow_id,
            execution_id=execution_id,
            resolve_step_id=resolve_step_id,
            actor=actor,
            approval_granted=approval_granted,
        ),
        goal=goal,
        workflow_type=workflow_type,
        store_id=store_id,
        sku=sku,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
    )
    base = persist_workflow_to_context(base, result.workflow)
    base["plan_snapshot"] = plan.model_dump(mode="json")
    return result, base


def cancel_workflow_in_context(
    context: dict[str, Any] | None,
    *,
    reason: str = "",
    actor: str | None = None,
    run_compensation: bool = False,
) -> dict[str, Any]:
    base = dict(context or {})
    snapshot = base.get("plan_snapshot")
    if not snapshot:
        return base
    plan = Plan.model_validate(snapshot)
    engine = get_workflow_engine()
    prior = load_workflow_from_context(base) or {}
    wf = engine.create(plan, execution_id=base.get("execution_id") or prior.get("execution_id"))
    if prior.get("workflow_id"):
        wf.workflow_id = str(prior["workflow_id"])
    if prior.get("status"):
        from workflow.types import WorkflowStatus

        try:
            wf.status = WorkflowStatus(str(prior["status"]))
        except Exception:  # noqa: BLE001
            pass
    wf = engine.cancel(
        wf, reason=reason, actor=actor, run_compensation=run_compensation
    )
    return persist_workflow_to_context(base, wf)


__all__ = [
    "attach_workflow_to_execution_context",
    "cancel_workflow_in_context",
    "get_workflow_engine",
    "reset_workflow_engine",
    "resume_workflow_for_execution",
    "run_workflow_for_execution",
    "workflow_health",
]

"""Planning service façade — Agent Runtime only."""

from __future__ import annotations

import logging
from typing import Any

from planner.contracts import ExecutionContext, Plan
from planner.factory import get_planner, planner_health, reset_planner

logger = logging.getLogger(__name__)


def _context_from_kwargs(
    *,
    goal: str,
    workflow: str,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    purchase_order_id: str | None = None,
    business_context: dict[str, Any] | None = None,
    actor: str = "agent",
    actor_role: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        execution_id=execution_id,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        store_id=store_id,
        sku=sku,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        workflow=workflow,
        goal=goal,
        actor=actor,
        actor_role=actor_role,
        business_context=dict(business_context or {}),
    )


def create_execution_plan(
    *,
    goal: str,
    workflow: str,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    purchase_order_id: str | None = None,
    business_context: dict[str, Any] | None = None,
    actor: str = "agent",
    actor_role: str | None = None,
) -> Plan:
    planner = get_planner()
    ctx = _context_from_kwargs(
        goal=goal,
        workflow=workflow,
        execution_id=execution_id,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        store_id=store_id,
        sku=sku,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        business_context=business_context,
        actor=actor,
        actor_role=actor_role,
    )
    return planner.create_plan(ctx)


def run_plan_until_blocked(
    plan: Plan,
    *,
    goal: str,
    workflow: str,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    business_context: dict[str, Any] | None = None,
) -> Plan:
    planner = get_planner()
    ctx = _context_from_kwargs(
        goal=goal,
        workflow=workflow,
        execution_id=execution_id,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        store_id=store_id,
        sku=sku,
        business_context=business_context,
    )
    return planner.execute(plan, ctx, stop_on_wait=True)


def resume_plan_execution(
    plan: Plan,
    *,
    goal: str,
    workflow: str,
    resolve_step_id: str | None = None,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
) -> Plan:
    planner = get_planner()
    ctx = _context_from_kwargs(
        goal=goal,
        workflow=workflow,
        execution_id=execution_id,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        store_id=store_id,
        sku=sku,
    )
    return planner.resume(plan, ctx, resolve_step_id=resolve_step_id)


def attach_plan_to_execution_context(
    context: dict[str, Any] | None,
    *,
    goal: str,
    workflow: str,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    execute: bool = False,
) -> tuple[dict[str, Any], Plan | None]:
    """
    Create (and optionally execute) a plan; attach ops summary to context.
    Returns (enriched_context, plan). Fail-soft on errors.
    """
    base = dict(context or {})
    plan: Plan | None = None
    try:
        plan = create_execution_plan(
            goal=goal,
            workflow=workflow,
            execution_id=execution_id,
            recommendation_id=recommendation_id or base.get("recommendation_id"),
            approval_id=approval_id or base.get("approval_id"),
            store_id=store_id or base.get("store_id"),
            sku=sku or base.get("sku"),
            business_context={
                k: base.get(k)
                for k in ("store_id", "sku", "mode", "question_type")
                if base.get(k) is not None
            },
        )
        if execute:
            plan = run_plan_until_blocked(
                plan,
                goal=goal,
                workflow=workflow,
                execution_id=execution_id,
                recommendation_id=plan.metadata.get("recommendation_id"),
                approval_id=plan.metadata.get("approval_id"),
                store_id=store_id or base.get("store_id"),
                sku=sku or base.get("sku"),
            )
        planner = get_planner()
        base["plan_ops"] = planner.ops_bundle(plan)
        base["task_graph"] = base["plan_ops"].get("task_graph")
        # Persist serializable plan for resume
        base["plan_snapshot"] = plan.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan_attach_failed execution_id=%s err=%s", execution_id, exc)
        base.setdefault(
            "plan_ops",
            {
                "plan_id": None,
                "status": "failed",
                "error": "plan_unavailable",
                "current_step": None,
                "completed_steps": [],
                "blocked_steps": [],
                "parallel_branches": [],
                "timeline": [],
                "resume_state": {"resumable": False},
            },
        )
    return base, plan


def planning_health() -> dict[str, Any]:
    return planner_health()


__all__ = [
    "attach_plan_to_execution_context",
    "create_execution_plan",
    "get_planner",
    "planning_health",
    "reset_planner",
    "resume_plan_execution",
    "run_plan_until_blocked",
]

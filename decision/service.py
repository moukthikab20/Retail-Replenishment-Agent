"""Decision service façade — Agent Runtime only."""

from __future__ import annotations

import logging
from typing import Any

from decision.context import assemble_decision_context, context_from_execution_dict
from decision.contracts import DecisionOutcome
from decision.factory import (
    decision_health,
    get_decision_engine,
    reset_decision_engine,
    validate_decision_strategy_configuration,
)

logger = logging.getLogger(__name__)


def evaluate_decision(
    *,
    execution_id: str | None = None,
    goal: str | None = None,
    workflow: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    actor: str | None = None,
    actor_role: str | None = None,
    business_context: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    enable_llm_advisor: bool | None = None,
) -> DecisionOutcome:
    from config import DECISION_ENABLED, DECISION_LLM_ADVISOR

    if not DECISION_ENABLED:
        # Minimal degraded outcome via engine path with wait_for_human — still typed.
        ctx = assemble_decision_context(
            execution_id=execution_id,
            goal=goal,
            workflow=workflow,
            store_id=store_id,
            sku=sku,
            recommendation_id=recommendation_id,
            actor_role=actor_role,
            business_context=business_context,
            memory=memory,
            policy=policy or {"disposition": "disabled"},
        )
        outcome = get_decision_engine().evaluate(ctx)
        outcome.degraded = True
        outcome.degradation_reason = "decision_disabled"
        return outcome

    ctx = assemble_decision_context(
        execution_id=execution_id,
        goal=goal,
        workflow=workflow,
        store_id=store_id,
        sku=sku,
        supplier_id=supplier_id,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        actor=actor,
        actor_role=actor_role,
        business_context=business_context,
        memory=memory,
        policy=policy,
        recommendation=recommendation,
        inventory=inventory,
    )
    engine = get_decision_engine()
    if enable_llm_advisor is not None:
        engine.llm_advisor_enabled = bool(enable_llm_advisor)
    return engine.evaluate(ctx)


def attach_decision_to_execution_context(
    context: dict[str, Any] | None,
    *,
    execution_id: str | None = None,
    goal: str | None = None,
    workflow: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    actor_role: str | None = None,
) -> dict[str, Any]:
    """
    Fail-soft: attach decision_ops to execution context.
    Never raises — planner/LLM continue if decision scoring fails.
    """
    base = dict(context or {})
    try:
        from config import DECISION_ENABLED

        if not DECISION_ENABLED:
            base["decision_ops"] = {
                "status": "degraded",
                "degraded": True,
                "degradation_reason": "decision_disabled",
                "winning_action": None,
            }
            return base

        memory = base.get("memory") if isinstance(base.get("memory"), dict) else {}
        outcome = evaluate_decision(
            execution_id=execution_id,
            goal=goal or base.get("goal"),
            workflow=workflow or base.get("workflow"),
            store_id=store_id or base.get("store_id"),
            sku=sku or base.get("sku"),
            supplier_id=base.get("supplier_id"),
            recommendation_id=recommendation_id or base.get("recommendation_id"),
            approval_id=approval_id or base.get("approval_id"),
            actor_role=actor_role or base.get("actor_role"),
            memory=memory,
            business_context={
                k: base.get(k)
                for k in (
                    "store_id",
                    "sku",
                    "recommendation",
                    "inventory",
                    "policy",
                    "policy_evaluation",
                    "erp_state",
                    "supplier_history",
                )
                if base.get(k) is not None
            },
            policy=base.get("policy_evaluation") or base.get("policy"),
            recommendation=base.get("recommendation")
            if isinstance(base.get("recommendation"), dict)
            else None,
            inventory=base.get("inventory") if isinstance(base.get("inventory"), dict) else None,
        )
        base["decision_ops"] = outcome.to_ops_summary()
        base["decision"] = {
            "evaluation_id": outcome.evaluation_id,
            "action": str(outcome.recommendation.action),
            "require_human": outcome.recommendation.require_human,
            "narrative": outcome.explanation.narrative,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision_attach_failed execution_id=%s err=%s", execution_id, exc)
        base["decision_ops"] = {
            "status": "degraded",
            "degraded": True,
            "degradation_reason": type(exc).__name__,
            "winning_action": None,
            "require_human": True,
        }
    return base


__all__ = [
    "attach_decision_to_execution_context",
    "context_from_execution_dict",
    "decision_health",
    "evaluate_decision",
    "get_decision_engine",
    "reset_decision_engine",
    "validate_decision_strategy_configuration",
]

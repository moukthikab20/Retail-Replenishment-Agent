"""Assemble DecisionContext from execution / business signals (read-only)."""

from __future__ import annotations

from typing import Any

from decision.contracts import DecisionContext, new_evaluation_id
from decision.validators import extract_policy_result


def assemble_decision_context(
    *,
    execution_id: str | None = None,
    goal: str | None = None,
    workflow: str | None = None,
    planner_objective: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    purchase_order_id: str | None = None,
    actor: str | None = None,
    actor_role: str | None = None,
    recommendation: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    supplier_history: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    semantic_knowledge: list[dict[str, Any]] | None = None,
    erp_state: dict[str, Any] | None = None,
    execution_history: list[dict[str, Any]] | None = None,
    human_approvals: list[dict[str, Any]] | None = None,
    conversation_context: str | None = None,
    identity: dict[str, Any] | None = None,
    business_context: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
    evaluation_id: str | None = None,
) -> DecisionContext:
    """Build a read-only DecisionContext. Does not mutate business state."""
    biz = dict(business_context or {})
    mem = dict(memory or {})
    # Prefer explicit semantic_knowledge; else pull from memory assembly shape.
    knowledge = list(semantic_knowledge or [])
    if not knowledge and isinstance(mem.get("retrieved_knowledge"), list):
        knowledge = list(mem.get("retrieved_knowledge") or [])

    policy_raw = policy or biz.get("policy") or biz.get("policy_evaluation") or {}
    if not isinstance(policy_raw, dict):
        policy_raw = {"disposition": str(policy_raw)}

    inv = dict(inventory or {})
    if not inv and isinstance(biz.get("inventory"), dict):
        inv = dict(biz["inventory"])

    rec = dict(recommendation or {})
    if not rec and isinstance(biz.get("recommendation"), dict):
        rec = dict(biz["recommendation"])

    return DecisionContext(
        evaluation_id=evaluation_id or new_evaluation_id(),
        execution_id=execution_id,
        goal=goal,
        workflow=workflow,
        planner_objective=planner_objective or goal,
        store_id=store_id or biz.get("store_id"),
        sku=sku or biz.get("sku"),
        supplier_id=supplier_id or biz.get("supplier_id"),
        recommendation_id=recommendation_id or biz.get("recommendation_id"),
        approval_id=approval_id or biz.get("approval_id"),
        purchase_order_id=purchase_order_id or biz.get("purchase_order_id"),
        actor=actor,
        actor_role=actor_role,
        recommendation=rec,
        inventory=inv,
        supplier_history=dict(supplier_history or biz.get("supplier_history") or {}),
        policy=extract_policy_result(policy_raw),
        memory=mem,
        semantic_knowledge=knowledge,
        erp_state=dict(erp_state or biz.get("erp_state") or {}),
        execution_history=list(execution_history or []),
        human_approvals=list(human_approvals or []),
        conversation_context=conversation_context,
        identity=dict(identity or {}),
        business_context=biz,
        extras=dict(extras or {}),
    )


def context_from_execution_dict(base: dict[str, Any] | None, **kwargs: Any) -> DecisionContext:
    data = dict(base or {})
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    return assemble_decision_context(
        execution_id=kwargs.get("execution_id") or data.get("execution_id"),
        goal=kwargs.get("goal") or data.get("goal"),
        workflow=kwargs.get("workflow") or data.get("workflow") or data.get("execution_type"),
        store_id=kwargs.get("store_id") or data.get("store_id"),
        sku=kwargs.get("sku") or data.get("sku"),
        supplier_id=kwargs.get("supplier_id") or data.get("supplier_id"),
        recommendation_id=kwargs.get("recommendation_id") or data.get("recommendation_id"),
        approval_id=kwargs.get("approval_id") or data.get("approval_id"),
        purchase_order_id=kwargs.get("purchase_order_id") or data.get("purchase_order_id"),
        actor=kwargs.get("actor") or data.get("actor"),
        actor_role=kwargs.get("actor_role") or data.get("actor_role"),
        memory=memory,
        semantic_knowledge=memory.get("retrieved_knowledge")
        if isinstance(memory, dict)
        else None,
        business_context={
            k: data.get(k)
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
            if data.get(k) is not None
        },
        conversation_context=data.get("conversation_context") or data.get("user_input"),
        identity={"actor": data.get("actor"), "actor_role": data.get("actor_role")},
        recommendation=data.get("recommendation") if isinstance(data.get("recommendation"), dict) else None,
        inventory=data.get("inventory") if isinstance(data.get("inventory"), dict) else None,
        policy=data.get("policy_evaluation") or data.get("policy"),
        **{k: v for k, v in kwargs.items() if k not in {
            "execution_id", "goal", "workflow", "store_id", "sku", "supplier_id",
            "recommendation_id", "approval_id", "purchase_order_id", "actor", "actor_role",
        }},
    )

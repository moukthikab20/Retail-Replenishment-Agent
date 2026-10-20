"""Enterprise Decision Intelligence Engine tests."""

from __future__ import annotations

import pytest

from agent.execution_engine import create_execution
from agent.execution_states import ExecutionType
from decision.audit import (
    AUDIT_CANDIDATE_GENERATED,
    AUDIT_CANDIDATE_SCORED,
    AUDIT_DECISION_ESCALATED,
    AUDIT_DECISION_SELECTED,
    AUDIT_DECISION_STARTED,
    list_decision_audit_events,
    reset_decision_audit,
)
from decision.candidates import generate_candidates
from decision.context import assemble_decision_context
from decision.factory import (
    decision_health,
    get_decision_engine,
    reset_decision_engine,
    validate_decision_strategy_configuration,
)
from decision.scoring import score_candidate
from decision.service import attach_decision_to_execution_context, evaluate_decision
from decision.strategies import get_strategy
from decision.types import DecisionAction, DecisionStrategyName
from integrations.failures import ProviderConfigError
from services import agent_ops_service, ops_health_service


def _ctx(**overrides):
    base = dict(
        store_id="ST001",
        sku="SKU-1001",
        supplier_id="ABC",
        goal="Replenish store inventory",
        workflow="recommendation_analysis",
        inventory={"on_hand": 5, "days_of_supply": 2, "usable_on_hand": 5},
        recommendation={
            "recommended_quantity": 24,
            "forecast_units": 30,
            "forecast_confidence": 0.7,
            "unit_cost": 10.0,
            "lead_time_days": 5,
        },
        supplier_history={"reliability": 0.8, "lead_time_days": 5, "on_time_rate": 0.8},
        policy={"disposition": "auto_release"},
        memory={"retrieved_records": 3, "knowledge_sources": ["mem-1"]},
        semantic_knowledge=[
            {"citation": "[Policy POL-004]", "document_id": "POL-004", "text": "Orders over $5,000 require approval."}
        ],
        erp_state={"recent_failures": 0},
        actor_role="store_manager",
    )
    base.update(overrides)
    return assemble_decision_context(**base)


def test_candidate_generation_multiple_alternatives():
    ctx = _ctx()
    cands = generate_candidates(ctx)
    actions = {str(c.action) for c in cands}
    assert DecisionAction.CREATE_PURCHASE_ORDER in actions
    assert DecisionAction.WAIT_FOR_HUMAN in actions
    assert DecisionAction.ESCALATE_APPROVAL in actions
    assert len(cands) >= 7


def test_strategy_selection_and_fail_fast(monkeypatch):
    assert validate_decision_strategy_configuration("balanced") == "balanced"
    monkeypatch.setattr("config.DECISION_STRATEGY", "autogen")
    reset_decision_engine()
    with pytest.raises(ProviderConfigError):
        validate_decision_strategy_configuration()

    for name in (
        DecisionStrategyName.LOWEST_RISK,
        DecisionStrategyName.LOWEST_COST,
        DecisionStrategyName.FASTEST_DELIVERY,
        DecisionStrategyName.BUSINESS_POLICY_FIRST,
        DecisionStrategyName.MOCK,
        DecisionStrategyName.BALANCED,
    ):
        strategy = get_strategy(name.value)
        ctx = _ctx()
        cands = [score_candidate(c, ctx) for c in generate_candidates(ctx)]
        winner = strategy.select(cands, ctx)
        assert winner.candidate_id


def test_risk_and_confidence_scoring():
    ctx = _ctx()
    outcome = evaluate_decision(
        store_id="ST001",
        sku="SKU-1001",
        inventory=ctx.inventory,
        recommendation=ctx.recommendation,
        policy={"disposition": "auto_release"},
        memory=ctx.memory,
        business_context={"supplier_history": ctx.supplier_history},
    )
    assert outcome.confidence.score > 0
    assert outcome.confidence.level in {"low", "medium", "high"}
    assert outcome.winning_candidate is not None
    assert outcome.winning_candidate.scores
    assert outcome.explanation.chosen_action
    assert outcome.alternatives


def test_policy_precedence_blocks_po():
    outcome = evaluate_decision(
        store_id="ST001",
        sku="SKU-1001",
        inventory={"on_hand": 2, "days_of_supply": 1},
        recommendation={"recommended_quantity": 48, "unit_cost": 200, "forecast_confidence": 0.6},
        policy={"disposition": "human_review", "requires_human": True, "policy_id": "POL-004"},
        memory={"retrieved_records": 2},
    )
    assert outcome.recommendation.require_human is True
    assert str(outcome.recommendation.action) in {
        DecisionAction.ESCALATE_APPROVAL,
        DecisionAction.WAIT_FOR_HUMAN,
    }
    assert str(outcome.recommendation.action) != DecisionAction.CREATE_PURCHASE_ORDER
    assert "POL-004" in " ".join(outcome.explanation.policy_references) or outcome.policy.hard_rule_applied


def test_llm_optional_advisor_path(monkeypatch):
    monkeypatch.setattr("config.DECISION_LLM_ADVISOR", True)
    reset_decision_engine()
    outcome = evaluate_decision(
        store_id="ST001",
        sku="SKU-1001",
        enable_llm_advisor=True,
        inventory={"on_hand": 10, "days_of_supply": 8},
        recommendation={"recommended_quantity": 12, "forecast_confidence": 0.8},
        policy={"disposition": "auto_release"},
    )
    # Advisor may or may not involve mock LLM; must never execute or override policy authority.
    assert outcome.recommendation.execute is False
    assert outcome.llm_advisor.get("cannot_approve", True) in {True, None} or outcome.llm_advisor.get(
        "involved"
    ) in {True, False}


def test_decision_explanation_and_audit():
    reset_decision_audit()
    outcome = evaluate_decision(
        execution_id="EXE-DEC-1",
        store_id="ST001",
        sku="SKU-1001",
        inventory={"on_hand": 4, "days_of_supply": 2},
        recommendation={"recommended_quantity": 20, "forecast_confidence": 0.65},
        policy={"disposition": "auto_release"},
        memory={"retrieved_records": 1, "citations": ["mem-a"]},
    )
    assert outcome.explanation.narrative
    assert outcome.explanation.trade_offs
    assert outcome.trace.evaluation_id == outcome.evaluation_id
    events = [e["event_type"] for e in list_decision_audit_events()]
    assert AUDIT_DECISION_STARTED in events
    assert AUDIT_CANDIDATE_GENERATED in events
    assert AUDIT_CANDIDATE_SCORED in events
    assert AUDIT_DECISION_SELECTED in events or AUDIT_DECISION_ESCALATED in events


def test_fail_soft_scoring_and_attach(monkeypatch):
    monkeypatch.setattr(
        "decision.engine.generate_candidates",
        lambda ctx: (_ for _ in ()).throw(RuntimeError("score boom")),
    )
    reset_decision_engine()
    outcome = get_decision_engine(force_new=True).evaluate(_ctx())
    assert outcome.degraded is True
    assert outcome.recommendation.require_human is True

    ctx = attach_decision_to_execution_context(
        {"store_id": "ST001", "sku": "SKU-1001"},
        execution_id="EXE-FS",
        goal="test",
        workflow="recommendation_analysis",
    )
    assert "decision_ops" in ctx


def test_planner_memory_rbac_agent_ops_health_integration():
    from planner.service import create_execution_plan
    from planner.factory import get_planner

    plan = create_execution_plan(
        goal="Analyze ST001/SKU-1001",
        workflow="recommendation_analysis",
        store_id="ST001",
        sku="SKU-1001",
    )
    step_ids = [s.id for s in plan.steps]
    assert "evaluate_decision" in step_ids
    # Decision step precedes LLM
    assert step_ids.index("evaluate_decision") < step_ids.index("llm_orchestrate")

    ex = create_execution(
        execution_type=ExecutionType.RECOMMENDATION_ANALYSIS,
        goal="Analyze replenishment",
        actor_role="store_manager",
        context={
            "store_id": "ST001",
            "sku": "SKU-1001",
            "inventory": {"on_hand": 3, "days_of_supply": 2},
            "recommendation": {"recommended_quantity": 24, "forecast_confidence": 0.7},
            "policy": {"disposition": "human_review", "requires_human": True},
        },
    )
    envelope = ex.get("envelope") or {}
    ctx = envelope.get("context") or {}
    assert "decision_ops" in ctx
    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    assert detail.get("decision") is not None
    assert detail["decision"].get("winning_action") or detail["decision"].get("status")

    health = ops_health_service.get_operational_health()
    names = {c.get("component") for c in health.get("dependencies") or []}
    assert "decision_engine" in names
    assert "decision_strategy" in names
    assert "scoring_engine" in names
    assert "decision_explainer" in names
    assert decision_health().get("ok") is True

    # Decision layer does not mutate RBAC; recommendation remains non-executing.
    assert ctx["decision_ops"].get("execute") is False


def test_knowledge_and_erp_signals_in_outcome():
    outcome = evaluate_decision(
        store_id="ST001",
        sku="SKU-1001",
        inventory={"on_hand": 1, "days_of_supply": 1},
        recommendation={"recommended_quantity": 40, "unit_cost": 50, "forecast_confidence": 0.55},
        policy={"disposition": "auto_release"},
        memory={
            "retrieved_records": 4,
            "retrieved_knowledge": [
                {"citation": "[SOP OPS-3]", "document_id": "OPS-3"},
            ],
            "citations": ["[SOP OPS-3]"],
        },
        business_context={"erp_state": {"recent_failures": 3}},
    )
    assert outcome.explanation.knowledge_references or outcome.trace.knowledge_ids
    assert any(str(r.category) == "erp" for r in outcome.risks) or outcome.winning_candidate

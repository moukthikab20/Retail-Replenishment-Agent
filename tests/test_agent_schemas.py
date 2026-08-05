"""Checkpoint 2 — structured output schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas import FollowUpAnswer, OrderExecutionResult, ReplenishmentAgentDecision


def _valid_decision_kwargs(**overrides):
    base = {
        "recommendation_id": "rec-1",
        "store_id": "ST001",
        "sku": "SKU-1001",
        "product_name": "Widget",
        "forecast_days": 7,
        "forecast_units": 42.0,
        "average_daily_sales": 6.0,
        "usable_on_hand": 10,
        "in_transit": 4,
        "open_order_quantity": 4,
        "safety_stock": 8,
        "days_of_supply": 2.3,
        "raw_quantity": 36.0,
        "agent_recommended_quantity": 36,
        "case_pack": 12,
        "risk": "stockout",
        "confidence": 0.8,
        "confidence_basis": ["forecast_method=moving_average"],
        "explanation": "Low cover relative to forecast.",
        "approval_required": True,
        "next_action": "review_recommendation",
        "tools_used": ["get_demand_forecast", "calculate_replenishment"],
        "warnings": [],
    }
    base.update(overrides)
    return base


def test_replenishment_agent_decision_accepts_valid_payload():
    decision = ReplenishmentAgentDecision(**_valid_decision_kwargs())
    assert decision.recommendation_id == "rec-1"
    assert decision.next_action == "review_recommendation"
    assert decision.risk == "stockout"
    assert decision.open_order_quantity == 4
    dumped = decision.model_dump(mode="json")
    assert dumped["agent_recommended_quantity"] == 36
    assert "required_approval_role" not in dumped


@pytest.mark.parametrize(
    "next_action",
    ["review_recommendation", "no_order_required", "manual_data_review", "blocked"],
)
def test_replenishment_agent_decision_next_actions(next_action):
    decision = ReplenishmentAgentDecision(
        **_valid_decision_kwargs(next_action=next_action)
    )
    assert decision.next_action == next_action


@pytest.mark.parametrize(
    "risk",
    ["stockout", "overstock", "balanced", "manual_review", "insufficient_data"],
)
def test_replenishment_agent_decision_risk_levels(risk):
    decision = ReplenishmentAgentDecision(**_valid_decision_kwargs(risk=risk))
    assert decision.risk == risk


def test_replenishment_agent_decision_rejects_legacy_next_action():
    with pytest.raises(ValidationError):
        ReplenishmentAgentDecision(
            **_valid_decision_kwargs(next_action="await_human_review")
        )


def test_replenishment_agent_decision_rejects_invalid_risk():
    with pytest.raises(ValidationError):
        ReplenishmentAgentDecision(**_valid_decision_kwargs(risk="critical"))


def test_replenishment_agent_decision_requires_core_fields():
    with pytest.raises(ValidationError):
        ReplenishmentAgentDecision(
            store_id="ST001",
            sku="SKU-1001",
            product_name="Widget",
            forecast_units=1.0,
            usable_on_hand=1,
            in_transit=0,
            safety_stock=1,
            agent_recommended_quantity=0,
            risk="balanced",
            explanation="missing recommendation_id",
        )


def test_follow_up_answer_schema():
    answer = FollowUpAnswer(
        recommendation_id="rec-1",
        question_type="explanation",
        answer="Cover is about 2.3 days at the current forecast.",
        verified_facts=["days_of_supply=2.3", "forecast_units=42"],
        assumptions=["Demand continues at the seven-day average."],
        unresolved_items=[],
        scenario_result=None,
        suggested_next_action="review_recommendation",
        tools_used=["get_recommendation"],
        can_change_business_state=False,
    )
    dumped = answer.model_dump(mode="json")
    assert dumped["recommendation_id"] == "rec-1"
    assert dumped["question_type"] == "explanation"
    assert len(dumped["verified_facts"]) == 2
    assert dumped["tools_used"] == ["get_recommendation"]
    assert dumped["can_change_business_state"] is False


@pytest.mark.parametrize(
    "question_type",
    [
        "explanation",
        "quantity_scenario",
        "delay_scenario",
        "missing_data",
        "policy_question",
        "prohibited_action",
        "general",
    ],
)
def test_follow_up_answer_question_types(question_type):
    answer = FollowUpAnswer(
        recommendation_id="rec-1",
        question_type=question_type,
        answer="ok",
    )
    assert answer.question_type == question_type


def test_follow_up_answer_rejects_unknown_question_type():
    with pytest.raises(ValidationError):
        FollowUpAnswer(
            recommendation_id="rec-1",
            question_type="approve_now",
            answer="nope",
        )


def test_follow_up_answer_forces_can_change_business_state_false():
    answer = FollowUpAnswer(
        recommendation_id="rec-1",
        question_type="quantity_scenario",
        answer="Hypothetical only.",
        can_change_business_state=True,
        scenario_result={
            "proposed_quantity": 12,
            "agent_recommended_quantity": 24,
            "hypothetical": True,
        },
    )
    assert answer.can_change_business_state is False
    dumped = answer.model_dump(mode="json")
    assert dumped["can_change_business_state"] is False
    assert dumped["scenario_result"]["proposed_quantity"] == 12


def test_follow_up_answer_rejects_non_json_scenario_result():
    with pytest.raises(ValidationError):
        FollowUpAnswer(
            recommendation_id="rec-1",
            question_type="quantity_scenario",
            answer="bad scenario",
            scenario_result={"fn": lambda: None},  # type: ignore[dict-item]
        )


def test_follow_up_answer_requires_recommendation_and_answer():
    with pytest.raises(ValidationError):
        FollowUpAnswer(answer="No id")


def test_order_execution_result_schema():
    result = OrderExecutionResult(
        run_id="run-1",
        approval_id="appr-1",
        purchase_order_id="po-1",
        status="order_created",
        agent_recommended_quantity=36,
        human_proposed_quantity=48,
        approved_final_quantity=48,
        message="Purchase order created.",
        next_action=None,
    )
    dumped = result.model_dump(mode="json")
    assert dumped["status"] == "order_created"
    assert dumped["agent_recommended_quantity"] == 36
    assert dumped["human_proposed_quantity"] == 48
    assert dumped["approved_final_quantity"] == 48


@pytest.mark.parametrize(
    "status",
    ["approval_pending", "approved", "rejected", "order_created", "order_failed"],
)
def test_order_execution_result_statuses(status):
    result = OrderExecutionResult(
        run_id="run-1",
        approval_id="appr-1",
        status=status,
        agent_recommended_quantity=10,
        human_proposed_quantity=10,
        approved_final_quantity=10 if status in {"approved", "order_created"} else None,
        message="ok",
    )
    assert result.status == status


def test_order_execution_result_rejects_unknown_status():
    with pytest.raises(ValidationError):
        OrderExecutionResult(
            run_id="run-1",
            approval_id="appr-1",
            status="shipped",
            agent_recommended_quantity=10,
            human_proposed_quantity=10,
            message="bad",
        )

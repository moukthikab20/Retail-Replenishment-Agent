"""Agent tool and orchestrator tests (no live OpenAI calls)."""

from __future__ import annotations

import pytest

from agent.orchestrator import build_replenishment_agent
from agent.runner import run_analysis
from agent.schemas import ReplenishmentAgentDecision
from agent.tools import ALL_TOOLS, create_mock_purchase_order
from services import (
    approval_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)


def test_agent_is_single_named_agent():
    agent = build_replenishment_agent(model="gpt-4o-mini")
    assert agent.name == "Retail Replenishment Agent"
    assert agent.output_type is ReplenishmentAgentDecision or getattr(
        agent, "output_type", None
    ) is not None


def test_tools_registered():
    names = {getattr(t, "name", None) or getattr(t, "__name__", "") for t in ALL_TOOLS}
    for required in [
        "get_product_details",
        "get_inventory_position",
        "get_open_orders",
        "get_demand_forecast",
        "calculate_replenishment",
        "assess_replenishment_risk",
        "create_recommendation_record",
        "get_recommendation",
        "get_human_review_status",
        "get_approval_status",
        "create_mock_purchase_order",
        "get_purchase_order_status",
    ]:
        assert required in names


def test_order_tool_needs_approval():
    assert create_mock_purchase_order.needs_approval is True


def test_deterministic_analysis_calls_pipeline_and_does_not_create_order(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "completed"
    assert decision["recommendation_id"]
    assert decision["agent_recommended_quantity"] >= 0
    assert decision["next_action"] in {
        "review_recommendation",
        "no_order_required",
        "manual_data_review",
        "blocked",
    }
    # Structured fields — do not rely on parsing explanation prose
    assert "agent_recommended_quantity" in decision
    assert "recommendation_id" in decision
    assert "forecast_units" in decision
    assert "open_order_quantity" in decision
    assert "case_pack" in decision
    assert isinstance(decision.get("tools_used"), list)
    assert "create_mock_purchase_order" not in decision.get("tools_used", [])
    # quantity comes from services, not invented prose
    rec = recommendation_service.get_recommendation(decision["recommendation_id"])
    assert rec["agent_recommended_quantity"] == decision["agent_recommended_quantity"]


def test_does_not_treat_chat_text_as_approval():
    rec = recommendation_service.create_recommendation_record("ST001", "SKU-1001", rationale="t")
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)
    # Chat-like string is not a decision API
    with pytest.raises(ValueError):
        approval_service.decide_approval(
            approval_id=approval.approval_id,
            decision="looks good, please approve",
            actor="alex.store",
            actor_role="store_manager",
        )


def test_creates_order_only_after_approval_and_preserves_three_quantities():
    rec = recommendation_service.create_recommendation_record("ST001", "SKU-1001", rationale="t")
    agent_qty = rec.agent_recommended_quantity
    case_pack = recommendation_service.get_recommendation(rec.recommendation_id)["case_pack"]
    human_qty = agent_qty + case_pack
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="manual",
        human_proposed_quantity=human_qty,
        override_reason="Increase cover",
        submitted_by="jamie.planner",
        actor_role="inventory_planner",
    )
    assert review.agent_recommended_quantity == agent_qty
    assert review.human_proposed_quantity == human_qty

    approval = approval_service.create_approval_request(review_id=review.review_id)
    with pytest.raises(ValueError):
        purchase_order_service.create_mock_purchase_order(approval.approval_id)

    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="casey.category",
        actor_role="category_manager",
    )
    po = purchase_order_service.create_mock_purchase_order(decided.approval_id)
    assert po.agent_recommended_quantity == agent_qty
    assert po.human_proposed_quantity == human_qty
    assert po.approved_final_quantity == human_qty
    assert po.purchase_order_id


def test_service_tools_do_not_invent_quantity():
    from services import product_service, inventory_service, forecast_service, replenishment_service

    product = product_service.get_product_details("SKU-1001")
    inventory = inventory_service.get_inventory_position("ST001", "SKU-1001")
    forecast = forecast_service.get_demand_forecast("ST001", "SKU-1001")
    result = replenishment_service.calculate_replenishment(
        store_id="ST001",
        sku="SKU-1001",
        forecast_units=forecast.forecast_units,
        inventory=inventory,
        product=product,
    )
    assert isinstance(result.recommended_quantity, int)

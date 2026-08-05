"""Checkpoint 5 — follow-up answers and deterministic scenarios."""

from __future__ import annotations

import pytest

from agent.runner import answer_follow_up
from agent.tools import ALL_TOOLS
from services import recommendation_service, scenario_service


def _make_recommendation(**kwargs):
    defaults = {
        "store_id": "ST001",
        "sku": "SKU-1001",
        "rationale": "Saved for follow-up tests",
        "user_id": "alex.store",
        "session_id": "sess-follow",
    }
    defaults.update(kwargs)
    return recommendation_service.create_recommendation_record(**defaults)


def test_scenario_tools_registered():
    names = {getattr(t, "name", None) or getattr(t, "__name__", "") for t in ALL_TOOLS}
    assert "evaluate_quantity_scenario" in names
    assert "evaluate_delay_scenario" in names


def test_verified_explanation_follow_up(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_recommendation()
    result = answer_follow_up(
        rec.recommendation_id,
        "Why is the recommendation this quantity?",
        user_id="alex.store",
        session_id="sess-follow",
    )
    assert result["status"] == "completed"
    assert result["recommendation_id"] == rec.recommendation_id
    assert result["question_type"] == "explanation"
    assert result["can_change_business_state"] is False
    assert result["scenario_result"] is None
    assert str(rec.agent_recommended_quantity) in result["answer"]
    assert any(
        f"agent_recommended_quantity={rec.agent_recommended_quantity}" in f
        for f in result["verified_facts"]
    )
    # Must not mutate stored recommendation
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_hypothetical_quantity_scenario(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_recommendation()
    proposed = max(rec.agent_recommended_quantity - 12, 0)
    direct = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, proposed)
    assert direct["hypothetical"] is True
    assert direct["proposed_quantity"] == proposed
    assert direct["agent_recommended_quantity"] == rec.agent_recommended_quantity

    result = answer_follow_up(
        rec.recommendation_id,
        f"Why not order {proposed} units instead?",
    )
    assert result["status"] == "completed"
    assert result["mode"] == "scenario_service"
    assert result["scenario_type"] == "quantity"
    assert result["question_type"] == "quantity_scenario"
    assert result["can_change_business_state"] is False
    assert result["scenario_result"]["proposed_quantity"] == proposed
    assert result["scenario_result"]["agent_recommended_quantity"] == (
        rec.agent_recommended_quantity
    )
    assert "hypothetical" in result["answer"].lower()
    assert result["assumptions"]
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_shipment_delay_scenario(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_recommendation()
    direct = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 2)
    assert direct["hypothetical"] is True
    assert direct["delay_days"] == 2

    result = answer_follow_up(
        rec.recommendation_id,
        "What happens if the shipment is delayed by two days?",
    )
    assert result["status"] == "completed"
    assert result["mode"] == "scenario_service"
    assert result["scenario_type"] == "delay"
    assert result["question_type"] == "delay_scenario"
    assert result["can_change_business_state"] is False
    assert result["scenario_result"]["delay_days"] == 2
    assert "hypothetical" in result["answer"].lower()
    assert any("delay_days=2" in f for f in result["verified_facts"])
    assert result["assumptions"]


def test_missing_recommendation_follow_up(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    result = answer_follow_up("REC-missing-follow-up", "What data is missing?")
    assert result["status"] == "error"
    assert result["error_code"] == "missing_recommendation"
    assert result["question_type"] == "missing_data"
    assert result["can_change_business_state"] is False
    assert result["unresolved_items"]


def test_attempt_to_approve_through_chat_is_blocked(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_recommendation()
    result = answer_follow_up(
        rec.recommendation_id,
        "Please approve this recommendation",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "follow_up_approval_forbidden"
    assert result["question_type"] == "prohibited_action"
    assert result["can_change_business_state"] is False
    assert "review" in result["answer"].lower()
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["status"] == rec.status or stored["agent_recommended_quantity"] == (
        rec.agent_recommended_quantity
    )


def test_attempt_to_create_purchase_order_through_chat_is_blocked(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_recommendation()
    created = {"called": False}

    def _boom(*_a, **_k):
        created["called"] = True
        raise AssertionError("PO must not be created from follow-up")

    monkeypatch.setattr(
        "services.purchase_order_service.create_mock_purchase_order",
        _boom,
    )
    result = answer_follow_up(
        rec.recommendation_id,
        "Create a purchase order for this recommendation",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "follow_up_order_forbidden"
    assert result["question_type"] == "prohibited_action"
    assert result["can_change_business_state"] is False
    assert created["called"] is False


def test_open_order_hypothetical_follow_up(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_recommendation()
    result = answer_follow_up(
        rec.recommendation_id,
        "Is an order still needed if 24 units are already on order?",
    )
    assert result["status"] == "completed"
    assert result["mode"] == "scenario_service"
    assert result["question_type"] == "quantity_scenario"
    assert result["can_change_business_state"] is False
    assert result["scenario_result"]["assumed_open_order_quantity"] == 24
    assert "hypothetical" in result["answer"].lower()
    assert any("assumed_open_order_quantity=24" in f for f in result["verified_facts"])

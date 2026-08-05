"""Checkpoint 6 — follow-up agent instructions and behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.instructions import FOLLOW_UP_INSTRUCTIONS
from agent.orchestrator import build_follow_up_agent, build_replenishment_agent
from agent.runner import answer_follow_up
from agent.schemas import FollowUpAnswer
from agent.tools import FOLLOW_UP_TOOLS
from services import recommendation_service, scenario_service


def _make_rec(**kwargs):
    defaults = {
        "store_id": "ST001",
        "sku": "SKU-1001",
        "rationale": "follow-up-agent",
        "user_id": "alex.store",
    }
    defaults.update(kwargs)
    return recommendation_service.create_recommendation_record(**defaults)


def test_follow_up_agent_reuses_same_agent_name_and_follow_up_answer_output():
    analysis = build_replenishment_agent(model="gpt-4o-mini")
    follow_up = build_follow_up_agent(model="gpt-4o-mini")
    assert follow_up.name == analysis.name == "Retail Replenishment Agent"
    assert follow_up.output_type is FollowUpAnswer or getattr(
        follow_up, "output_type", None
    ) is FollowUpAnswer


def test_follow_up_agent_uses_dedicated_instructions_and_tools():
    agent = build_follow_up_agent(model="gpt-4o-mini")
    assert agent.instructions == FOLLOW_UP_INSTRUCTIONS
    names = {t.name for t in agent.tools}
    assert names == {t.name for t in FOLLOW_UP_TOOLS}
    assert "evaluate_quantity_scenario" in names
    assert "evaluate_delay_scenario" in names
    assert "create_mock_purchase_order" not in names
    assert "create_approval_request" not in names


def test_follow_up_instructions_cover_required_rules():
    text = FOLLOW_UP_INSTRUCTIONS.lower()
    for phrase in (
        "get_recommendation",
        "verified tool results",
        "assumptions",
        "never change the stored recommendation",
        "never create or edit a human review",
        "never approve or reject an approval",
        "never create a purchase order",
        "approve it",
        "place the order",
        "go ahead",
        "evaluate_quantity_scenario",
        "evaluate_delay_scenario",
        "missing",
        "hypothetical",
        "followupanswer",
        "concise and business-readable",
        "sdk internals",
    ):
        assert phrase in text


def test_explanation_uses_stored_recommendation(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    result = answer_follow_up(
        rec.recommendation_id,
        "Why is this quantity recommended?",
        user_id="alex.store",
    )
    assert result["status"] == "completed"
    assert result["question_type"] == "explanation"
    assert str(rec.agent_recommended_quantity) in result["answer"]
    assert any(
        f"agent_recommended_quantity={rec.agent_recommended_quantity}" in f
        for f in result["verified_facts"]
    )
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_quantity_scenario_uses_quantity_tool_path(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    proposed = max(rec.agent_recommended_quantity - 12, 0)
    called = {"qty": False}

    real = scenario_service.evaluate_quantity_scenario

    def _wrap(recommendation_id: str, proposed_quantity: int):
        called["qty"] = True
        return real(recommendation_id, proposed_quantity)

    monkeypatch.setattr(
        "agent.runner.scenario_service.evaluate_quantity_scenario", _wrap
    )
    result = answer_follow_up(
        rec.recommendation_id,
        f"Why not order {proposed} units instead?",
        user_id="alex.store",
    )
    assert called["qty"] is True
    assert result["question_type"] == "quantity_scenario"
    assert result["scenario_result"]["proposed_quantity"] == proposed
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_delay_scenario_uses_delay_tool_path(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    called = {"delay": False}
    real = scenario_service.evaluate_delay_scenario

    def _wrap(recommendation_id: str, delay_days: int):
        called["delay"] = True
        return real(recommendation_id, delay_days)

    monkeypatch.setattr("agent.runner.scenario_service.evaluate_delay_scenario", _wrap)
    result = answer_follow_up(
        rec.recommendation_id,
        "What happens if the shipment is delayed by two days?",
        user_id="alex.store",
    )
    assert called["delay"] is True
    assert result["question_type"] == "delay_scenario"
    assert result["scenario_result"]["delay_days"] == 2


def test_recommendation_remains_unchanged_after_follow_up(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    before = recommendation_service.get_recommendation(rec.recommendation_id)
    answer_follow_up(rec.recommendation_id, "Explain the risk.", user_id="alex.store")
    after = recommendation_service.get_recommendation(rec.recommendation_id)
    assert after["agent_recommended_quantity"] == before["agent_recommended_quantity"]
    assert after["status"] == before["status"]
    assert after["rationale"] == before["rationale"]


def test_approval_request_through_chat_is_rejected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    for question in (
        "Please approve this recommendation",
        "Approve it",
        "Go ahead",
    ):
        result = answer_follow_up(rec.recommendation_id, question, user_id="alex.store")
        assert result["status"] == "error"
        assert result["question_type"] == "prohibited_action"
        assert result["error_code"] == "follow_up_approval_forbidden"


def test_order_request_through_chat_is_rejected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    for question in (
        "Create a purchase order for this recommendation",
        "Place the order",
    ):
        result = answer_follow_up(rec.recommendation_id, question, user_id="alex.store")
        assert result["status"] == "error"
        assert result["question_type"] == "prohibited_action"
        assert result["error_code"] == "follow_up_order_forbidden"


def test_missing_recommendation_returns_controlled_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    result = answer_follow_up("REC-missing-agent", "Why this quantity?")
    assert result["status"] == "error"
    assert result["error_code"] == "missing_recommendation"
    assert result["unresolved_items"]


def test_agent_path_forces_follow_up_answer_output_type(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec = _make_rec()
    captured: dict = {}

    def _capture(agent, prompt, **kwargs):
        captured["agent"] = agent
        captured["output_type"] = getattr(agent, "output_type", None)
        return SimpleNamespace(
            interruptions=[],
            final_output=FollowUpAnswer(
                recommendation_id=rec.recommendation_id,
                question_type="explanation",
                answer="Verified from saved recommendation.",
                verified_facts=[f"agent_recommended_quantity={rec.agent_recommended_quantity}"],
                can_change_business_state=False,
            ),
        )

    monkeypatch.setattr("agent.runner._execute_runner", _capture)
    monkeypatch.setattr("agent.runner.build_follow_up_agent", MagicMock(side_effect=build_follow_up_agent))

    # Bypass deterministic scenario/explanation routing by asking a vague question
    # while still exercising the agent runner path.
    out = answer_follow_up(
        rec.recommendation_id,
        "Summarize the recommendation context for me.",
        user_id="alex.store",
    )
    assert out["status"] == "completed"
    assert captured["output_type"] is FollowUpAnswer
    assert out["can_change_business_state"] is False

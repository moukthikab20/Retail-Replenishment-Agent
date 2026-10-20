"""Checkpoint 10 — agent orchestration role (not replenishment math)."""

from __future__ import annotations

from agent.instructions import AGENT_INSTRUCTIONS, FOLLOW_UP_INSTRUCTIONS
from agent.orchestrator import build_follow_up_agent, build_replenishment_agent
from agent.tools import ALL_TOOLS, ANALYSIS_TOOLS, FOLLOW_UP_TOOLS, ORDER_TOOLS


def test_instructions_state_orchestration_not_math_role():
    text = AGENT_INSTRUCTIONS.lower()
    assert "orchestration" in text or "orchestrate" in text
    assert "never perform replenishment arithmetic" in text
    assert "never invent inventory" in text or "never invent" in text
    assert "approve an order through chat" in text or "approve" in text
    assert "deterministic services" in text
    assert "case-pack" in text or "case pack" in text


def test_follow_up_instructions_forbid_chat_mutations():
    text = FOLLOW_UP_INSTRUCTIONS.lower()
    assert "get_policy_evaluation" in text
    assert "get_order_terms" in text
    assert "get_forecast" in text
    assert "never change the stored recommendation" in text
    assert "never create a purchase order" in text
    assert "can_change_business_state to false" in text


def test_analysis_agent_excludes_order_mutation_tools():
    agent = build_replenishment_agent()
    names = {getattr(t, "name", None) for t in agent.tools}
    assert "calculate_replenishment" in names
    assert "create_mock_purchase_order" not in names
    assert "create_approval_request" not in names
    assert names == {t.name for t in ANALYSIS_TOOLS}


def test_follow_up_agent_has_required_read_tools():
    agent = build_follow_up_agent()
    names = {getattr(t, "name", None) for t in agent.tools}
    for required in (
        "get_recommendation",
        "get_inventory_position",
        "get_forecast",
        "get_policy_evaluation",
        "get_order_terms",
        "get_recommendation_history",
        "evaluate_quantity_scenario",
        "evaluate_delay_scenario",
    ):
        assert required in names
    assert "create_mock_purchase_order" not in names
    assert names == {t.name for t in FOLLOW_UP_TOOLS}


def test_order_tools_remain_available_on_full_surface():
    names = {t.name for t in ALL_TOOLS}
    assert "create_mock_purchase_order" in names
    assert {t.name for t in ORDER_TOOLS}.issubset(names)

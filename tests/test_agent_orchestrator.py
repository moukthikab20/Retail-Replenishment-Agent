"""Checkpoint 3 — orchestrator instructions and mocked analysis behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from agents import MaxTurnsExceeded

from agent.instructions import (
    AGENT_INSTRUCTIONS,
    ANALYSIS_FORBIDDEN_DURING_ANALYSIS,
    ANALYSIS_TOOL_SEQUENCE,
)
from agent.orchestrator import (
    analysis_max_turns,
    build_replenishment_agent,
    forbidden_analysis_tools,
    required_analysis_tools,
)
from agent.runner import run_analysis
from agent.schemas import ReplenishmentAgentDecision
from config import AS_OF_DATE, OPENAI_MODEL
from models.inventory import InventoryPosition
from services import inventory_service, recommendation_service


def test_agent_uses_configured_model_and_output_type(monkeypatch):
    monkeypatch.setattr("agent.orchestrator.OPENAI_MODEL", "configured-test-model")
    agent = build_replenishment_agent()
    assert agent.name == "Retail Replenishment Agent"
    assert agent.model == "configured-test-model"
    assert agent.output_type is ReplenishmentAgentDecision or getattr(
        agent, "output_type", None
    ) is not None
    # Default builder must not hardcode a divergent model name.
    assert OPENAI_MODEL


def test_max_turns_is_finite_and_from_config():
    turns = analysis_max_turns()
    assert isinstance(turns, int)
    assert 1 <= turns <= 50


def test_instructions_require_exact_analysis_sequence():
    text = AGENT_INSTRUCTIONS.lower()
    for tool in ANALYSIS_TOOL_SEQUENCE:
        assert tool in AGENT_INSTRUCTIONS
    assert "get_open_orders" in text
    assert "calculate_replenishment" in text
    assert "create_mock_purchase_order" in text
    assert "never perform replenishment arithmetic" in text
    assert "manual_data_review" in text
    assert "blocked" in text
    assert required_analysis_tools() == ANALYSIS_TOOL_SEQUENCE
    assert forbidden_analysis_tools() == ANALYSIS_FORBIDDEN_DURING_ANALYSIS


def test_deterministic_analysis_calls_required_tools_and_stops(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "completed"
    tools = decision["tools_used"]
    for required in ANALYSIS_TOOL_SEQUENCE:
        assert required in tools
    for forbidden in ANALYSIS_FORBIDDEN_DURING_ANALYSIS:
        assert forbidden not in tools
    assert decision["recommendation_id"]
    assert decision["next_action"] in {
        "review_recommendation",
        "no_order_required",
        "manual_data_review",
        "blocked",
    }


def test_does_not_skip_replenishment_or_invent_quantity(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = run_analysis("ST001", "SKU-1001")
    assert "calculate_replenishment" in decision["tools_used"]
    rec = recommendation_service.get_recommendation(decision["recommendation_id"])
    assert decision["agent_recommended_quantity"] == rec["agent_recommended_quantity"]
    assert isinstance(decision["agent_recommended_quantity"], int)


def test_handles_existing_open_orders(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    open_orders = inventory_service.get_open_orders("ST001", "SKU-1001")
    decision = run_analysis("ST001", "SKU-1001")
    assert "get_open_orders" in decision["tools_used"]
    assert decision["open_order_quantity"] == open_orders["open_order_quantity"]
    assert decision["open_order_quantity"] == decision["in_transit"]


def test_does_not_create_purchase_order_during_analysis(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    created = {"called": False}

    def _boom(*_a, **_k):
        created["called"] = True
        raise AssertionError("create_mock_purchase_order must not run during analysis")

    monkeypatch.setattr(
        "services.purchase_order_service.create_mock_purchase_order",
        _boom,
    )
    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "completed"
    assert created["called"] is False
    assert "create_mock_purchase_order" not in decision.get("tools_used", [])


def test_handles_missing_inventory(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")

    def _missing(store_id, sku):
        raise ValueError(f"No inventory for store={store_id} sku={sku}")

    monkeypatch.setattr(
        "services.inventory_service.get_inventory_position",
        _missing,
    )
    monkeypatch.setattr(
        "services.recommendation_service.inventory_service.get_inventory_position",
        _missing,
    )
    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "error"
    assert decision["error_code"] == "missing_inventory"
    assert decision["next_action"] == "manual_data_review"
    assert decision["risk"] == "insufficient_data"
    assert decision.get("recommendation_id") is None
    assert decision.get("agent_recommended_quantity") is None


def test_handles_stale_inventory(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")

    as_of = datetime.fromisoformat(AS_OF_DATE).replace(tzinfo=timezone.utc)
    stale_position = InventoryPosition(
        store_id="ST001",
        sku="SKU-1001",
        on_hand=18,
        reserved=0,
        in_transit=12,
        safety_stock=10,
        updated_at=as_of - timedelta(days=30),
        store_name="Downtown Flagship",
    )

    monkeypatch.setattr(
        "services.inventory_service.get_inventory_position",
        lambda store_id, sku: stale_position,
    )
    monkeypatch.setattr(
        "services.recommendation_service.inventory_service.get_inventory_position",
        lambda store_id, sku: stale_position,
    )
    monkeypatch.setattr(
        "agent.runner.inventory_service.get_inventory_position",
        lambda store_id, sku: stale_position,
    )

    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "completed"
    assert decision["risk"] == "manual_review"
    assert decision["next_action"] == "manual_data_review"
    assert any("stale" in w.lower() for w in decision.get("warnings", []))


def test_max_turns_exceeded_returns_controlled_business_error(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test-not-used")

    def _raise(*_a, **_k):
        raise MaxTurnsExceeded("too many turns")

    monkeypatch.setattr("agent.runner.Runner.run_sync", _raise)
    monkeypatch.setattr("agent.runner.build_replenishment_agent", build_replenishment_agent)

    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "error"
    assert decision["error_code"] == "max_turns_exceeded"
    assert decision["next_action"] == "blocked"
    assert decision["risk"] == "manual_review"
    assert "sdk" not in decision["message"].lower()
    assert "MaxTurnsExceeded" not in decision["message"]
    assert decision.get("agent_recommended_quantity") is None


def test_mocked_sdk_success_returns_structured_output(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test-not-used")
    structured = ReplenishmentAgentDecision(
        recommendation_id="rec-mock",
        store_id="ST001",
        sku="SKU-1001",
        product_name="Widget",
        forecast_days=7,
        forecast_units=40.0,
        average_daily_sales=5.0,
        usable_on_hand=10,
        in_transit=0,
        open_order_quantity=0,
        safety_stock=8,
        raw_quantity=36.0,
        agent_recommended_quantity=36,
        case_pack=12,
        risk="stockout",
        explanation="Tool-backed recommendation.",
        next_action="review_recommendation",
        tools_used=list(ANALYSIS_TOOL_SEQUENCE),
    )

    monkeypatch.setattr(
        "agent.runner.Runner.run_sync",
        lambda *_a, **_k: SimpleNamespace(
            interruptions=[],
            final_output=structured,
            to_state=lambda: SimpleNamespace(to_json=lambda: {}),
        ),
    )
    decision = run_analysis("ST001", "SKU-1001")
    assert decision["status"] == "completed"
    assert decision["recommendation_id"] == "rec-mock"
    assert decision["agent_recommended_quantity"] == 36
    assert decision["next_action"] == "review_recommendation"
    assert "create_mock_purchase_order" not in decision["tools_used"]


def test_inventory_tool_reports_stale_flag():
    as_of = datetime.fromisoformat(AS_OF_DATE).replace(tzinfo=timezone.utc)
    fresh = InventoryPosition(
        store_id="ST001",
        sku="SKU-1001",
        on_hand=1,
        in_transit=0,
        safety_stock=1,
        updated_at=as_of,
    )
    stale = InventoryPosition(
        store_id="ST001",
        sku="SKU-1001",
        on_hand=1,
        in_transit=0,
        safety_stock=1,
        updated_at=as_of - timedelta(days=30),
    )
    assert inventory_service.is_inventory_stale(fresh) is False
    assert inventory_service.is_inventory_stale(stale) is True

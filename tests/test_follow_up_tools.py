"""Checkpoint 3 — read-only follow-up tools."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agent.context import ReplenishmentRunContext
from agent.orchestrator import build_follow_up_agent
from agent.tools import (
    FOLLOW_UP_TOOLS,
    get_demand_forecast,
    get_forecast,
    get_inventory_position,
    get_open_orders,
    get_order_terms,
    get_policy_evaluation,
    get_product_details,
    get_recommendation,
    get_recommendation_history,
)
from agents.tool_context import ToolContext
from services import recommendation_service


FOLLOW_UP_TOOL_NAMES = {
    "get_recommendation",
    "get_inventory_position",
    "get_forecast",
    "get_demand_forecast",
    "get_policy_evaluation",
    "get_order_terms",
    "get_recommendation_history",
    "get_product_details",
    "get_open_orders",
    "evaluate_quantity_scenario",
    "evaluate_delay_scenario",
}

MUTATING_TOOL_NAMES = {
    "create_recommendation_record",
    "create_approval_request",
    "create_mock_purchase_order",
}


def _invoke(tool: Any, payload: dict[str, Any]) -> Any:
    args_json = json.dumps(payload)

    async def _run() -> Any:
        ctx = ToolContext(
            context=ReplenishmentRunContext(run_id="RUN-follow-up-tools", actor="tester"),
            tool_name=tool.name,
            tool_call_id="call-follow-up",
            tool_arguments=args_json,
        )
        return await tool.on_invoke_tool(ctx, args_json)

    return asyncio.run(_run())


def test_follow_up_tools_are_read_only_orchestration_surface():
    names = {t.name for t in FOLLOW_UP_TOOLS}
    assert names == FOLLOW_UP_TOOL_NAMES
    assert names.isdisjoint(MUTATING_TOOL_NAMES)
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
    for tool in FOLLOW_UP_TOOLS:
        assert tool.needs_approval is False


def test_follow_up_agent_uses_read_only_tools_only():
    agent = build_follow_up_agent(model="gpt-4o-mini")
    names = {getattr(t, "name", None) for t in agent.tools}
    assert names == FOLLOW_UP_TOOL_NAMES
    assert names.isdisjoint(MUTATING_TOOL_NAMES)


def test_get_recommendation_read_only():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="history-base"
    )
    before = recommendation_service.get_recommendation(rec.recommendation_id)
    result = _invoke(get_recommendation, {"recommendation_id": rec.recommendation_id})
    assert result["recommendation_id"] == rec.recommendation_id
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "agent_recommended_quantity" in result
    after = recommendation_service.get_recommendation(rec.recommendation_id)
    assert after["agent_recommended_quantity"] == before["agent_recommended_quantity"]
    assert after["status"] == before["status"]


def test_get_recommendation_missing_is_controlled_error():
    result = _invoke(get_recommendation, {"recommendation_id": "REC-does-not-exist"})
    text = str(result).lower()
    assert "not found" in text or "error" in text


def test_get_product_details_read_only():
    result = _invoke(
        get_product_details, {"store_id": "ST001", "sku": "SKU-1001"}
    )
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "product_name" in result
    assert "case_pack" in result
    json.dumps(result)


def test_get_inventory_position_read_only():
    result = _invoke(
        get_inventory_position, {"store_id": "ST001", "sku": "SKU-1001"}
    )
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "on_hand" in result
    assert "usable_on_hand" in result
    assert "in_transit" in result
    json.dumps(result)


def test_get_open_orders_read_only():
    result = _invoke(get_open_orders, {"store_id": "ST001", "sku": "SKU-1001"})
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "open_order_quantity" in result
    assert isinstance(result["open_orders"], list)
    json.dumps(result)


def test_get_demand_forecast_read_only():
    result = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7},
    )
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "forecast_units" in result
    assert result.get("forecast_days", 7) == 7
    json.dumps(result)


def test_get_demand_forecast_rejects_invalid_horizon():
    result = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 0},
    )
    text = str(result).lower()
    assert "forecast_days" in text or "error" in text


def test_get_recommendation_history_returns_newest_first():
    older = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="older-hist"
    )
    newer = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="newer-hist"
    )
    # Different SKU must not appear.
    recommendation_service.create_recommendation_record(
        "ST001", "SKU-1002", rationale="other-sku"
    )

    result = _invoke(
        get_recommendation_history,
        {"store_id": "ST001", "sku": "SKU-1001", "limit": 10},
    )
    assert result["status"] == "ok"
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert result["count"] >= 2
    ids = [item["recommendation_id"] for item in result["recommendations"]]
    assert newer.recommendation_id in ids
    assert older.recommendation_id in ids
    assert all(item["sku"] == "SKU-1001" for item in result["recommendations"])
    assert ids.index(newer.recommendation_id) < ids.index(older.recommendation_id)
    json.dumps(result)

    # History is read-only — quantities unchanged.
    stored = recommendation_service.get_recommendation(newer.recommendation_id)
    assert stored["agent_recommended_quantity"] == newer.agent_recommended_quantity


def test_get_recommendation_history_respects_limit():
    for i in range(3):
        recommendation_service.create_recommendation_record(
            "ST001", "SKU-1001", rationale=f"limit-{i}"
        )
    result = _invoke(
        get_recommendation_history,
        {"store_id": "ST001", "sku": "SKU-1001", "limit": 2},
    )
    assert result["limit"] == 2
    assert len(result["recommendations"]) <= 2


def test_get_recommendation_history_rejects_invalid_limit():
    result = _invoke(
        get_recommendation_history,
        {"store_id": "ST001", "sku": "SKU-1001", "limit": 0},
    )
    text = str(result).lower()
    assert "limit" in text or "error" in text


def test_unknown_store_is_controlled_domain_error():
    result = _invoke(
        get_product_details,
        {"store_id": "ST-NOPE", "sku": "SKU-1001"},
    )
    text = str(result).lower()
    assert "unknown store" in text or "error" in text


def test_get_forecast_matches_demand_forecast_tool():
    a = _invoke(get_forecast, {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7})
    b = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7},
    )
    assert a["forecast_units"] == b["forecast_units"]
    assert a["store_id"] == "ST001"


def test_get_policy_evaluation_returns_persisted_eval():
    from services import batch_run_service, policy_service

    policy_service.ensure_default_policy()
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="tester",
    )
    rec_id = next(i["recommendation_id"] for i in run["items"] if i.get("recommendation_id"))
    result = _invoke(get_policy_evaluation, {"recommendation_id": rec_id})
    assert result["status"] == "ok"
    assert result["recommendation_id"] == rec_id
    assert result["source"] == "persisted_recommendation"
    assert "disposition" in result
    assert "failed_rules" in result


def test_get_order_terms_does_not_invent_lead_time():
    result = _invoke(get_order_terms, {"store_id": "ST001", "sku": "SKU-1001"})
    assert result["status"] == "ok"
    assert result["case_pack"] >= 1
    assert result["lead_time_known"] is False
    assert result["supplier_lead_time_days"] is None

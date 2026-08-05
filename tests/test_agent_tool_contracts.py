"""Checkpoint 1 — contract tests for every agent tool."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agent.context import ReplenishmentRunContext
from agent.tools import (
    ALL_TOOLS,
    ANALYSIS_TOOLS,
    FOLLOW_UP_TOOLS,
    ORDER_TOOLS,
    assess_replenishment_risk,
    calculate_replenishment,
    create_mock_purchase_order,
    create_recommendation_record,
    get_approval_status,
    get_demand_forecast,
    get_human_review_status,
    get_inventory_position,
    get_open_orders,
    get_product_details,
    get_purchase_order_status,
    get_recommendation,
    get_recommendation_history,
)
from agents.tool_context import ToolContext
from services import (
    approval_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)
from services.errors import AppError


REQUIRED_TOOL_NAMES = {
    "get_product_details",
    "get_inventory_position",
    "get_open_orders",
    "get_demand_forecast",
    "calculate_replenishment",
    "assess_replenishment_risk",
    "create_recommendation_record",
    "get_recommendation",
    "get_recommendation_history",
    "get_human_review_status",
    "get_approval_status",
    "create_mock_purchase_order",
    "get_purchase_order_status",
}


def _invoke(tool: Any, payload: dict[str, Any]) -> Any:
    args_json = json.dumps(payload)

    async def _run() -> Any:
        ctx = ToolContext(
            context=ReplenishmentRunContext(run_id="RUN-contract", actor="tester"),
            tool_name=tool.name,
            tool_call_id="call-contract",
            tool_arguments=args_json,
        )
        return await tool.on_invoke_tool(ctx, args_json)

    return asyncio.run(_run())


def test_required_tools_registered():
    names = {t.name for t in ALL_TOOLS}
    assert REQUIRED_TOOL_NAMES.issubset(names)
    analysis_names = {t.name for t in ANALYSIS_TOOLS}
    assert "get_open_orders" in analysis_names
    assert "create_mock_purchase_order" in {t.name for t in ORDER_TOOLS}


def test_create_mock_purchase_order_needs_approval():
    assert create_mock_purchase_order.needs_approval is True
    for tool in ANALYSIS_TOOLS:
        assert tool.needs_approval is False


def test_get_product_details_contract():
    result = _invoke(
        get_product_details, {"store_id": "ST001", "sku": "SKU-1001"}
    )
    assert result["sku"] == "SKU-1001"
    assert result["store_id"] == "ST001"
    assert "product_name" in result
    assert "case_pack" in result


def test_get_inventory_position_contract():
    result = _invoke(
        get_inventory_position, {"store_id": "ST001", "sku": "SKU-1001"}
    )
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "on_hand" in result
    assert "usable_on_hand" in result
    assert "in_transit" in result


def test_get_open_orders_contract():
    result = _invoke(get_open_orders, {"store_id": "ST001", "sku": "SKU-1001"})
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert "open_order_quantity" in result
    assert isinstance(result["open_orders"], list)
    assert result["status"] == "ok"


def test_get_demand_forecast_contract():
    result = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7},
    )
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    assert float(result["forecast_units"]) >= 0
    assert int(result["forecast_days"]) == 7


def test_calculate_replenishment_uses_forecast_units():
    forecast = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7},
    )
    result = _invoke(
        calculate_replenishment,
        {
            "store_id": "ST001",
            "sku": "SKU-1001",
            "forecast_units": float(forecast["forecast_units"]),
        },
    )
    assert "recommended_quantity" in result
    assert isinstance(result["recommended_quantity"], int)
    assert result["recommended_quantity"] >= 0


def test_assess_replenishment_risk_contract():
    forecast = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7},
    )
    replenishment = _invoke(
        calculate_replenishment,
        {
            "store_id": "ST001",
            "sku": "SKU-1001",
            "forecast_units": float(forecast["forecast_units"]),
        },
    )
    result = _invoke(
        assess_replenishment_risk,
        {
            "store_id": "ST001",
            "sku": "SKU-1001",
            "recommended_quantity": replenishment["recommended_quantity"],
        },
    )
    assert "risk_level" in result
    assert isinstance(result.get("reasons"), list)


def test_create_and_get_recommendation_contract():
    forecast = _invoke(
        get_demand_forecast,
        {"store_id": "ST001", "sku": "SKU-1001", "forecast_days": 7},
    )
    replenishment = _invoke(
        calculate_replenishment,
        {
            "store_id": "ST001",
            "sku": "SKU-1001",
            "forecast_units": float(forecast["forecast_units"]),
        },
    )
    risk = _invoke(
        assess_replenishment_risk,
        {
            "store_id": "ST001",
            "sku": "SKU-1001",
            "recommended_quantity": replenishment["recommended_quantity"],
        },
    )
    created = _invoke(
        create_recommendation_record,
        {
            "store_id": "ST001",
            "sku": "SKU-1001",
            "forecast_result": {
                "forecast_units": float(forecast["forecast_units"]),
                "average_daily_sales": float(forecast["average_daily_sales"]),
                "forecast_days": 7,
                "method": forecast.get("method"),
                "store_id": "ST001",
                "sku": "SKU-1001",
            },
            "replenishment_result": {
                "recommended_quantity": replenishment["recommended_quantity"],
                "raw_quantity": float(replenishment["raw_quantity"]),
                "case_pack": int(replenishment["case_pack"]),
                "days_of_supply": replenishment.get("days_of_supply"),
                "constraints_applied": replenishment.get("constraints_applied") or [],
            },
            "risk_result": {
                "risk_level": risk["risk_level"],
                "reasons": risk.get("reasons") or [],
                "projected_days_of_supply": risk.get("projected_days_of_supply"),
            },
        },
    )
    assert created["recommendation_id"]
    assert created["agent_recommended_quantity"] == replenishment["recommended_quantity"]
    fetched = _invoke(
        get_recommendation, {"recommendation_id": created["recommendation_id"]}
    )
    assert fetched["recommendation_id"] == created["recommendation_id"]


def test_get_human_review_status_by_review_id():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="contract"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
    )
    result = _invoke(get_human_review_status, {"review_id": review.review_id})
    assert result["review_id"] == review.review_id
    assert result["status"] in {"submitted", "pending", "approved", "rejected"} or result[
        "review"
    ]


def test_get_approval_status_contract():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="contract"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)
    result = _invoke(get_approval_status, {"approval_id": approval.approval_id})
    assert result["approval_id"] == approval.approval_id
    assert result["status"] == "pending"


def test_create_mock_purchase_order_rejects_pending_and_accepts_approved_only():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="contract"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)

    # Service rejects pending approvals (tool wraps this as an error string under SDK).
    with pytest.raises((AppError, ValueError)):
        purchase_order_service.create_mock_purchase_order(approval.approval_id)

    pending_tool_result = _invoke(
        create_mock_purchase_order, {"approval_id": approval.approval_id}
    )
    assert isinstance(pending_tool_result, str) or (
        isinstance(pending_tool_result, dict)
        and pending_tool_result.get("status") not in {None, "ok"}
    ) or "pending" in str(pending_tool_result).lower() or "cannot" in str(
        pending_tool_result
    ).lower() or "error" in str(pending_tool_result).lower()

    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="casey.category",
        actor_role="category_manager",
    )
    # Service path validates approval_id-only contract, quantities, and idempotency.
    po = purchase_order_service.create_mock_purchase_order(decided.approval_id)
    assert po.purchase_order_id
    assert po.approved_final_quantity is not None
    assert po.agent_recommended_quantity == rec.agent_recommended_quantity

    po2 = purchase_order_service.create_mock_purchase_order(decided.approval_id)
    assert po2.purchase_order_id == po.purchase_order_id

    status = _invoke(
        get_purchase_order_status, {"purchase_order_id": po.purchase_order_id}
    )
    assert status.get("purchase_order_id") == po.purchase_order_id or "status" in status


def test_unknown_store_returns_controlled_error():
    result = _invoke(
        get_product_details,
        {"store_id": "NOPE", "sku": "SKU-1001"},
    )
    text = str(result).lower()
    assert "unknown store" in text or "error" in text or "nope" in text


def test_get_recommendation_history_contract():
    first = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="hist-a"
    )
    second = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="hist-b"
    )
    result = _invoke(
        get_recommendation_history,
        {"store_id": "ST001", "sku": "SKU-1001", "limit": 10},
    )
    assert result["status"] == "ok"
    assert result["store_id"] == "ST001"
    assert result["sku"] == "SKU-1001"
    ids = {item["recommendation_id"] for item in result["recommendations"]}
    assert first.recommendation_id in ids
    assert second.recommendation_id in ids
    follow_up_names = {t.name for t in FOLLOW_UP_TOOLS}
    assert "get_recommendation_history" in follow_up_names
    assert "create_mock_purchase_order" not in follow_up_names


def test_tools_do_not_accept_quantity_on_purchase_order_schema():
    schema = create_mock_purchase_order.params_json_schema
    props = schema.get("properties") or {}
    assert "approval_id" in props
    assert "store_id" not in props
    assert "sku" not in props
    assert "quantity" not in props
    assert "approved_final_quantity" not in props

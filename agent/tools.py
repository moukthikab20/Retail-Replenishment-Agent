"""Narrowly scoped agent tools that call deterministic services only."""

from __future__ import annotations

import logging
from typing import Any

from agents import RunContextWrapper, function_tool

from agent.context import ReplenishmentRunContext
from services import (
    approval_service,
    forecast_service,
    human_review_service,
    inventory_service,
    product_service,
    purchase_order_service,
    recommendation_service,
    replenishment_service,
    risk_service,
)

logger = logging.getLogger(__name__)


def _log_tool(name: str, args: dict[str, Any], result: Any) -> None:
    logger.info("tool_call name=%s args=%s result_keys=%s", name, args, list(result) if isinstance(result, dict) else type(result))


def _ctx(wrapper: RunContextWrapper[ReplenishmentRunContext] | None) -> ReplenishmentRunContext | None:
    return wrapper.context if wrapper is not None else None


@function_tool
def get_product_details(sku: str) -> dict[str, Any]:
    """Get product master details for a SKU."""
    product = product_service.get_product_details(sku)
    result = product.model_dump(mode="json")
    _log_tool("get_product_details", {"sku": sku}, result)
    return result


@function_tool
def get_inventory_position(store_id: str, sku: str) -> dict[str, Any]:
    """Get inventory position for a store/SKU."""
    position = inventory_service.get_inventory_position(store_id, sku)
    result = position.model_dump(mode="json")
    result["usable_on_hand"] = position.usable_on_hand
    _log_tool("get_inventory_position", {"store_id": store_id, "sku": sku}, result)
    return result


@function_tool
def get_demand_forecast(store_id: str, sku: str) -> dict[str, Any]:
    """Get the deterministic seven-day demand forecast."""
    forecast = forecast_service.get_demand_forecast(store_id, sku)
    result = forecast.model_dump(mode="json")
    _log_tool("get_demand_forecast", {"store_id": store_id, "sku": sku}, result)
    return result


@function_tool
def calculate_replenishment(store_id: str, sku: str) -> dict[str, Any]:
    """Calculate replenishment quantity using deterministic Python arithmetic only."""
    product = product_service.get_product_details(sku)
    inventory = inventory_service.get_inventory_position(store_id, sku)
    forecast = forecast_service.get_demand_forecast(store_id, sku)
    replenishment = replenishment_service.calculate_replenishment(
        store_id=store_id,
        sku=sku,
        forecast_units=forecast.forecast_units,
        inventory=inventory,
        product=product,
    )
    result = replenishment.model_dump(mode="json")
    _log_tool("calculate_replenishment", {"store_id": store_id, "sku": sku}, result)
    return result


@function_tool
def assess_replenishment_risk(store_id: str, sku: str) -> dict[str, Any]:
    """Assess replenishment risk using configured deterministic thresholds."""
    product = product_service.get_product_details(sku)
    inventory = inventory_service.get_inventory_position(store_id, sku)
    forecast = forecast_service.get_demand_forecast(store_id, sku)
    replenishment = replenishment_service.calculate_replenishment(
        store_id=store_id,
        sku=sku,
        forecast_units=forecast.forecast_units,
        inventory=inventory,
        product=product,
    )
    result = risk_service.assess_replenishment_risk(
        days_of_supply=replenishment.days_of_supply,
        recommended_quantity=replenishment.recommended_quantity,
        forecast_units=forecast.forecast_units,
        on_hand=inventory.on_hand,
        usable_on_hand=inventory.usable_on_hand,
        method=forecast.method,
    )
    _log_tool("assess_replenishment_risk", {"store_id": store_id, "sku": sku}, result)
    return result


@function_tool
def create_recommendation_record(store_id: str, sku: str, rationale: str) -> dict[str, Any]:
    """Persist a recommendation using deterministic service outputs plus your explanation."""
    recommendation = recommendation_service.create_recommendation_record(
        store_id,
        sku,
        rationale=rationale,
        actor="agent",
    )
    result = recommendation_service.get_recommendation(recommendation.recommendation_id)
    _log_tool(
        "create_recommendation_record",
        {"store_id": store_id, "sku": sku},
        result,
    )
    return result


@function_tool
def get_recommendation(recommendation_id: str) -> dict[str, Any]:
    """Fetch a stored recommendation by ID."""
    result = recommendation_service.get_recommendation(recommendation_id)
    _log_tool("get_recommendation", {"recommendation_id": recommendation_id}, result)
    return result


@function_tool
def get_human_review_status(recommendation_id: str) -> dict[str, Any]:
    """Read the stored human review for a recommendation. Do not modify it."""
    result = human_review_service.get_human_review_status(recommendation_id)
    _log_tool("get_human_review_status", {"recommendation_id": recommendation_id}, result)
    return result


@function_tool
def create_approval_request(review_id: str) -> dict[str, Any]:
    """Create a formal pending approval request from a submitted human review."""
    approval = approval_service.create_approval_request(review_id=review_id)
    result = approval.model_dump(mode="json")
    _log_tool("create_approval_request", {"review_id": review_id}, result)
    return result


@function_tool
def check_approval_status(approval_id: str) -> dict[str, Any]:
    """Check formal approval status. Chat text is never treated as approval."""
    result = approval_service.check_approval_status(approval_id)
    _log_tool("check_approval_status", {"approval_id": approval_id}, result)
    return result


@function_tool(needs_approval=True)
def create_mock_purchase_order(approval_id: str) -> dict[str, Any]:
    """Create a mock purchase order ONLY from an approved approval_id. Sensitive tool."""
    po = purchase_order_service.create_mock_purchase_order(approval_id)
    result = po.model_dump(mode="json")
    _log_tool("create_mock_purchase_order", {"approval_id": approval_id}, result)
    return result


@function_tool
def get_purchase_order_status(purchase_order_id: str) -> dict[str, Any]:
    """Get mock purchase order status by ID."""
    result = purchase_order_service.get_purchase_order_status(purchase_order_id)
    _log_tool("get_purchase_order_status", {"purchase_order_id": purchase_order_id}, result)
    return result


ALL_TOOLS = [
    get_product_details,
    get_inventory_position,
    get_demand_forecast,
    calculate_replenishment,
    assess_replenishment_risk,
    create_recommendation_record,
    get_recommendation,
    get_human_review_status,
    create_approval_request,
    check_approval_status,
    create_mock_purchase_order,
    get_purchase_order_status,
]

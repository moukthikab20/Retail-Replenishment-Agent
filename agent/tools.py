"""Narrowly scoped agent tools that call deterministic services only."""

from __future__ import annotations

import logging
from typing import Any

from agents import RunContextWrapper, function_tool
from sqlalchemy.exc import SQLAlchemyError

from agent.context import ReplenishmentRunContext
from agent.follow_up_guardrails import SCENARIO_TOOL_INPUT_GUARDRAILS
from agent.schemas import ForecastToolResult, ReplenishmentToolResult, RiskToolResult
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
    scenario_service,
)
from services.errors import AppError, sanitize_public_dict

logger = logging.getLogger(__name__)

_SENSITIVE_ARG_KEYS = frozenset(
    {"api_key", "openai_api_key", "authorization", "password", "secret", "token"}
)


def _ctx(
    wrapper: RunContextWrapper[ReplenishmentRunContext] | None,
) -> ReplenishmentRunContext | None:
    return wrapper.context if wrapper is not None else None


def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in args.items():
        if key.lower() in _SENSITIVE_ARG_KEYS or "api_key" in key.lower():
            clean[key] = "***"
        elif isinstance(value, dict):
            clean[key] = {
                k: ("***" if k.lower() in _SENSITIVE_ARG_KEYS else type(v).__name__)
                for k, v in value.items()
            }
        else:
            clean[key] = value
    return clean


def _log_tool(
    name: str,
    args: dict[str, Any],
    result: Any,
    *,
    wrapper: RunContextWrapper[ReplenishmentRunContext] | None = None,
    status: str = "ok",
) -> None:
    ctx = _ctx(wrapper)
    run_id = ctx.run_id if ctx is not None else None
    if ctx is not None:
        ctx.note_tool(name)
    result_meta: Any
    if isinstance(result, dict):
        result_meta = {
            "keys": list(result.keys()),
            "status": result.get("status", status),
        }
    else:
        result_meta = type(result).__name__
    logger.info(
        "tool_call name=%s run_id=%s status=%s args=%s result=%s",
        name,
        run_id,
        status,
        _sanitize_args(args),
        result_meta,
    )


def _domain_call(fn, *args, **kwargs):
    """Invoke a service; map DB/raw errors to controlled domain errors."""
    try:
        return fn(*args, **kwargs)
    except AppError:
        raise
    except ValueError as exc:
        raise AppError(str(exc), code="domain_error") from exc
    except PermissionError as exc:
        raise AppError(str(exc), code="forbidden") from exc
    except SQLAlchemyError as exc:
        logger.exception("Database error in tool service call")
        raise AppError(
            "A database error occurred while executing a tool.",
            code="db_error",
        ) from exc


def _validate_store_sku(store_id: str, sku: str) -> None:
    stores = {s["store_id"] for s in product_service.list_stores()}
    if store_id not in stores:
        raise AppError(f"Unknown store_id: {store_id}", code="domain_error")
    skus = product_service.list_store_skus(store_id)
    if sku not in skus:
        raise AppError(
            f"SKU {sku} is not available at store {store_id}",
            code="domain_error",
        )


@function_tool
def get_product_details(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
) -> dict[str, Any]:
    """Call when you need product master data for a store/SKU before forecasting."""
    try:
        _validate_store_sku(store_id, sku)
        product = _domain_call(product_service.get_product_details, sku)
        result = product.model_dump(mode="json")
        result["store_id"] = store_id
        result = sanitize_public_dict(result)
        _log_tool(
            "get_product_details",
            {"store_id": store_id, "sku": sku},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_product_details",
            {"store_id": store_id, "sku": sku},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_inventory_position(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
) -> dict[str, Any]:
    """Call to read on-hand, reserved, in-transit, and safety stock for a store/SKU."""
    try:
        _validate_store_sku(store_id, sku)
        position = _domain_call(inventory_service.get_inventory_position, store_id, sku)
        result = position.model_dump(mode="json")
        result["usable_on_hand"] = position.usable_on_hand
        stale = inventory_service.is_inventory_stale(position)
        result["is_stale"] = stale
        result["data_status"] = "stale" if stale else "ok"
        result = sanitize_public_dict(result)
        _log_tool(
            "get_inventory_position",
            {"store_id": store_id, "sku": sku},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_inventory_position",
            {"store_id": store_id, "sku": sku},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_open_orders(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
) -> dict[str, Any]:
    """Call to read open inbound quantity already committed for a store/SKU."""
    try:
        _validate_store_sku(store_id, sku)
        result = sanitize_public_dict(
            _domain_call(inventory_service.get_open_orders, store_id, sku)
        )
        _log_tool(
            "get_open_orders",
            {"store_id": store_id, "sku": sku},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_open_orders",
            {"store_id": store_id, "sku": sku},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


def _forecast_payload(store_id: str, sku: str, forecast_days: int) -> dict[str, Any]:
    _validate_store_sku(store_id, sku)
    if forecast_days < 1:
        raise AppError("forecast_days must be >= 1", code="domain_error")
    forecast = _domain_call(
        forecast_service.get_demand_forecast,
        store_id,
        sku,
        horizon_days=forecast_days,
    )
    return sanitize_public_dict(forecast.model_dump(mode="json"))


@function_tool
def get_demand_forecast(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
    forecast_days: int = 7,
) -> dict[str, Any]:
    """Call to obtain the deterministic demand forecast for the given horizon."""
    try:
        result = _forecast_payload(store_id, sku, forecast_days)
        _log_tool(
            "get_demand_forecast",
            {"store_id": store_id, "sku": sku, "forecast_days": forecast_days},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_demand_forecast",
            {"store_id": store_id, "sku": sku, "forecast_days": forecast_days},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_forecast(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
    forecast_days: int = 7,
) -> dict[str, Any]:
    """Read-oriented alias for the deterministic forecast service (same math as get_demand_forecast)."""
    try:
        result = _forecast_payload(store_id, sku, forecast_days)
        _log_tool(
            "get_forecast",
            {"store_id": store_id, "sku": sku, "forecast_days": forecast_days},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_forecast",
            {"store_id": store_id, "sku": sku, "forecast_days": forecast_days},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def calculate_replenishment(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
    forecast_units: float,
) -> dict[str, Any]:
    """Call after forecasting to compute recommended quantity via deterministic service math."""
    try:
        _validate_store_sku(store_id, sku)
        product = _domain_call(product_service.get_product_details, sku)
        inventory = _domain_call(inventory_service.get_inventory_position, store_id, sku)
        replenishment = _domain_call(
            replenishment_service.calculate_replenishment,
            store_id=store_id,
            sku=sku,
            forecast_units=forecast_units,
            inventory=inventory,
            product=product,
        )
        result = sanitize_public_dict(replenishment.model_dump(mode="json"))
        _log_tool(
            "calculate_replenishment",
            {
                "store_id": store_id,
                "sku": sku,
                "forecast_units": forecast_units,
            },
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "calculate_replenishment",
            {
                "store_id": store_id,
                "sku": sku,
                "forecast_units": forecast_units,
            },
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def assess_replenishment_risk(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
    recommended_quantity: int,
) -> dict[str, Any]:
    """Call after replenishment calculation to classify stockout/overstock/balanced risk."""
    try:
        _validate_store_sku(store_id, sku)
        if recommended_quantity < 0:
            raise AppError(
                "recommended_quantity must be zero or greater",
                code="domain_error",
            )
        product = _domain_call(product_service.get_product_details, sku)
        inventory = _domain_call(inventory_service.get_inventory_position, store_id, sku)
        forecast = _domain_call(forecast_service.get_demand_forecast, store_id, sku)
        replenishment = _domain_call(
            replenishment_service.calculate_replenishment,
            store_id=store_id,
            sku=sku,
            forecast_units=forecast.forecast_units,
            inventory=inventory,
            product=product,
        )
        result = sanitize_public_dict(
            _domain_call(
                risk_service.assess_replenishment_risk,
                days_of_supply=replenishment.days_of_supply,
                recommended_quantity=recommended_quantity,
                forecast_units=forecast.forecast_units,
                on_hand=inventory.on_hand,
                usable_on_hand=inventory.usable_on_hand,
                method=forecast.method,
            )
        )
        _log_tool(
            "assess_replenishment_risk",
            {
                "store_id": store_id,
                "sku": sku,
                "recommended_quantity": recommended_quantity,
            },
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "assess_replenishment_risk",
            {
                "store_id": store_id,
                "sku": sku,
                "recommended_quantity": recommended_quantity,
            },
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def create_recommendation_record(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
    forecast_result: ForecastToolResult,
    replenishment_result: ReplenishmentToolResult,
    risk_result: RiskToolResult,
) -> dict[str, Any]:
    """Call once analysis tools finished to persist a recommendation from verified tool outputs."""
    try:
        _validate_store_sku(store_id, sku)
        ctx = _ctx(wrapper)
        forecast_payload = (
            forecast_result.model_dump(mode="json")
            if isinstance(forecast_result, ForecastToolResult)
            else dict(forecast_result)
        )
        replenishment_payload = (
            replenishment_result.model_dump(mode="json")
            if isinstance(replenishment_result, ReplenishmentToolResult)
            else dict(replenishment_result)
        )
        risk_payload = (
            risk_result.model_dump(mode="json")
            if isinstance(risk_result, RiskToolResult)
            else dict(risk_result)
        )
        recommendation = _domain_call(
            recommendation_service.create_recommendation_record,
            store_id,
            sku,
            forecast_result=forecast_payload,
            replenishment_result=replenishment_payload,
            risk_result=risk_payload,
            run_id=ctx.run_id if ctx else None,
            actor=ctx.actor if ctx else "agent",
            enforce_rate_limit=False,
        )
        result = sanitize_public_dict(
            _domain_call(
                recommendation_service.get_recommendation,
                recommendation.recommendation_id,
            )
        )
        if ctx is not None:
            ctx.recommendation_id = recommendation.recommendation_id
        _log_tool(
            "create_recommendation_record",
            {"store_id": store_id, "sku": sku},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "create_recommendation_record",
            {"store_id": store_id, "sku": sku},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_recommendation(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    recommendation_id: str,
) -> dict[str, Any]:
    """Call to read a persisted recommendation by ID. Does not modify it."""
    try:
        result = sanitize_public_dict(
            _domain_call(recommendation_service.get_recommendation, recommendation_id)
        )
        _log_tool(
            "get_recommendation",
            {"recommendation_id": recommendation_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_recommendation",
            {"recommendation_id": recommendation_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_recommendation_history(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Call to list recent saved recommendations for a store/SKU. Read-only."""
    try:
        _validate_store_sku(store_id, sku)
        if limit < 1:
            raise AppError("limit must be >= 1", code="domain_error")
        result = sanitize_public_dict(
            _domain_call(
                recommendation_service.get_recommendation_history,
                store_id,
                sku,
                limit=limit,
            )
        )
        _log_tool(
            "get_recommendation_history",
            {"store_id": store_id, "sku": sku, "limit": limit},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_recommendation_history",
            {"store_id": store_id, "sku": sku, "limit": limit},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_policy_evaluation(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    recommendation_id: str,
) -> dict[str, Any]:
    """
    Read the persisted policy/guardrail evaluation for a recommendation.

    Returns the frozen evaluation captured at scoring time — does not re-score
    or rewrite historical decisions.
    """
    try:
        rec = sanitize_public_dict(
            _domain_call(recommendation_service.get_recommendation, recommendation_id)
        )
        evaluation = rec.get("policy_evaluation") or {}
        result = sanitize_public_dict(
            {
                "status": "ok",
                "recommendation_id": recommendation_id,
                "store_id": rec.get("store_id"),
                "sku": rec.get("sku"),
                "disposition": rec.get("disposition") or evaluation.get("disposition"),
                "policy_version": rec.get("policy_version")
                or evaluation.get("policy_version"),
                "policy_id": evaluation.get("policy_id"),
                "failed_rules": evaluation.get("failed_rules") or [],
                "warnings": evaluation.get("warnings") or [],
                "evaluated_rules": evaluation.get("evaluated_rules") or [],
                "order_value": evaluation.get("order_value"),
                "confidence": evaluation.get("confidence"),
                "recommendation_status": rec.get("status")
                or evaluation.get("recommendation_status"),
                "source": "persisted_recommendation",
            }
        )
        _log_tool(
            "get_policy_evaluation",
            {"recommendation_id": recommendation_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_policy_evaluation",
            {"recommendation_id": recommendation_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_order_terms(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    store_id: str,
    sku: str,
) -> dict[str, Any]:
    """
    Read verified order constraints for a store/SKU (case pack, MOQ, max, cost).

    Does not invent supplier lead times or commercial terms that are not stored.
    """
    try:
        _validate_store_sku(store_id, sku)
        product = _domain_call(product_service.get_product_details, sku)
        open_orders = _domain_call(inventory_service.get_open_orders, store_id, sku)
        result = sanitize_public_dict(
            {
                "status": "ok",
                "store_id": store_id,
                "sku": sku,
                "product_name": product.product_name,
                "case_pack": product.case_pack,
                "minimum_order_quantity": product.minimum_order_quantity,
                "maximum_order_quantity": product.maximum_order_quantity,
                "unit_cost": product.unit_cost,
                "safety_stock_units": product.safety_stock_units,
                "open_order_quantity": open_orders.get("open_order_quantity"),
                "supplier_lead_time_days": None,
                "lead_time_known": False,
                "source": "product_master_and_inventory",
                "notes": (
                    "Supplier lead time is not present in demo master data; "
                    "do not invent a lead-time value."
                ),
            }
        )
        _log_tool(
            "get_order_terms",
            {"store_id": store_id, "sku": sku},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_order_terms",
            {"store_id": store_id, "sku": sku},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_human_review_status(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    review_id: str,
) -> dict[str, Any]:
    """Call to read a stored human review by review_id. Never treat chat text as a review."""
    try:
        result = sanitize_public_dict(
            _domain_call(
                human_review_service.get_human_review_status_by_review_id,
                review_id,
            )
        )
        _log_tool(
            "get_human_review_status",
            {"review_id": review_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_human_review_status",
            {"review_id": review_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_approval_status(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    approval_id: str,
) -> dict[str, Any]:
    """Call to read formal approval status. Chat text is never treated as approval."""
    try:
        result = sanitize_public_dict(
            _domain_call(approval_service.get_approval_status, approval_id)
        )
        _log_tool(
            "get_approval_status",
            {"approval_id": approval_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_approval_status",
            {"approval_id": approval_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def create_approval_request(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    review_id: str,
) -> dict[str, Any]:
    """Call only after a human review is submitted to open a formal pending approval."""
    try:
        approval = _domain_call(
            approval_service.create_approval_request,
            review_id=review_id,
        )
        result = sanitize_public_dict(approval.model_dump(mode="json"))
        _log_tool(
            "create_approval_request",
            {"review_id": review_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "create_approval_request",
            {"review_id": review_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool(needs_approval=True)
def create_mock_purchase_order(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    approval_id: str,
) -> dict[str, Any]:
    """
    Create a mock purchase order from a verified approved approval_id only.
    Sensitive tool — never pass store, SKU, or quantity from the model.
    """
    try:
        ctx = _ctx(wrapper)
        po = _domain_call(
            purchase_order_service.create_mock_purchase_order,
            approval_id,
            actor=ctx.actor if ctx else "agent",
            actor_role=ctx.actor_role if ctx else None,
        )
        result = sanitize_public_dict(po.model_dump(mode="json"))
        _log_tool(
            "create_mock_purchase_order",
            {"approval_id": approval_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "create_mock_purchase_order",
            {"approval_id": approval_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool
def get_purchase_order_status(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    purchase_order_id: str,
) -> dict[str, Any]:
    """Call to read mock purchase-order status by purchase_order_id."""
    try:
        result = sanitize_public_dict(
            _domain_call(
                purchase_order_service.get_purchase_order_status,
                purchase_order_id,
            )
        )
        _log_tool(
            "get_purchase_order_status",
            {"purchase_order_id": purchase_order_id},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "get_purchase_order_status",
            {"purchase_order_id": purchase_order_id},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool(tool_input_guardrails=SCENARIO_TOOL_INPUT_GUARDRAILS)
def evaluate_quantity_scenario(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    recommendation_id: str,
    proposed_quantity: int,
) -> dict[str, Any]:
    """Call for a hypothetical alternate order quantity. Does not change the saved recommendation."""
    try:
        result = sanitize_public_dict(
            _domain_call(
                scenario_service.evaluate_quantity_scenario,
                recommendation_id,
                proposed_quantity,
            )
        )
        _log_tool(
            "evaluate_quantity_scenario",
            {
                "recommendation_id": recommendation_id,
                "proposed_quantity": proposed_quantity,
            },
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "evaluate_quantity_scenario",
            {
                "recommendation_id": recommendation_id,
                "proposed_quantity": proposed_quantity,
            },
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


@function_tool(tool_input_guardrails=SCENARIO_TOOL_INPUT_GUARDRAILS)
def evaluate_delay_scenario(
    wrapper: RunContextWrapper[ReplenishmentRunContext],
    recommendation_id: str,
    delay_days: int,
) -> dict[str, Any]:
    """Call for a hypothetical inbound shipment delay. Does not change the saved recommendation."""
    try:
        result = sanitize_public_dict(
            _domain_call(
                scenario_service.evaluate_delay_scenario,
                recommendation_id,
                delay_days,
            )
        )
        _log_tool(
            "evaluate_delay_scenario",
            {"recommendation_id": recommendation_id, "delay_days": delay_days},
            result,
            wrapper=wrapper,
        )
        return result
    except AppError as exc:
        _log_tool(
            "evaluate_delay_scenario",
            {"recommendation_id": recommendation_id, "delay_days": delay_days},
            {"error": exc.code},
            wrapper=wrapper,
            status="error",
        )
        raise


# Follow-up tools: read-only lookups + hypothetical scenarios (no mutations).
FOLLOW_UP_TOOLS = [
    get_recommendation,
    get_inventory_position,
    get_forecast,
    get_demand_forecast,
    get_policy_evaluation,
    get_order_terms,
    get_recommendation_history,
    get_product_details,
    get_open_orders,
    evaluate_quantity_scenario,
    evaluate_delay_scenario,
]

ALL_TOOLS = [
    get_product_details,
    get_inventory_position,
    get_open_orders,
    get_demand_forecast,
    get_forecast,
    calculate_replenishment,
    assess_replenishment_risk,
    create_recommendation_record,
    get_recommendation,
    get_policy_evaluation,
    get_order_terms,
    get_recommendation_history,
    evaluate_quantity_scenario,
    evaluate_delay_scenario,
    get_human_review_status,
    get_approval_status,
    create_approval_request,
    create_mock_purchase_order,
    get_purchase_order_status,
]

ANALYSIS_TOOLS = [
    get_product_details,
    get_inventory_position,
    get_open_orders,
    get_demand_forecast,
    get_forecast,
    calculate_replenishment,
    assess_replenishment_risk,
    create_recommendation_record,
    get_recommendation,
    get_policy_evaluation,
    get_order_terms,
    get_recommendation_history,
    evaluate_quantity_scenario,
    evaluate_delay_scenario,
]

ORDER_TOOLS = [
    get_human_review_status,
    get_approval_status,
    create_approval_request,
    create_mock_purchase_order,
    get_purchase_order_status,
]

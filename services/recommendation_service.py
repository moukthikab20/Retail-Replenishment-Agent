"""Recommendation creation service (deterministic persistence)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database.connection import get_session
from models.recommendation import Recommendation
from repositories import audit_repository, recommendation_repository
from services import (
    forecast_service,
    inventory_service,
    isolation_service,
    product_service,
    rate_limit_service,
    replenishment_service,
    risk_service,
)


def build_analysis(store_id: str, sku: str) -> dict[str, Any]:
    """Run deterministic forecast/replenishment/risk pipeline."""
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
    risk = risk_service.assess_replenishment_risk(
        days_of_supply=replenishment.days_of_supply,
        recommended_quantity=replenishment.recommended_quantity,
        forecast_units=forecast.forecast_units,
        on_hand=inventory.on_hand,
        usable_on_hand=inventory.usable_on_hand,
        method=forecast.method,
    )
    return {
        "product": product,
        "inventory": inventory,
        "forecast": forecast,
        "replenishment": replenishment,
        "risk": risk,
    }


def create_recommendation_record(
    store_id: str,
    sku: str,
    *,
    rationale: str = "",
    forecast_result: dict[str, Any] | None = None,
    replenishment_result: dict[str, Any] | None = None,
    risk_result: dict[str, Any] | None = None,
    run_id: str | None = None,
    actor: str = "agent",
    user_id: str | None = None,
    session_id: str | None = None,
    enforce_rate_limit: bool = True,
) -> Recommendation:
    """
    Persist a recommendation.

    When forecast/replenishment/risk dicts from tools are provided, those
    verified values are stored. Otherwise the deterministic pipeline runs
    (used by the no-API-key fallback).
    """
    if enforce_rate_limit:
        rate_limit_service.assert_within_agent_run_limit(user_id)

    product = product_service.get_product_details(sku)
    inventory = inventory_service.get_inventory_position(store_id, sku)

    if forecast_result and replenishment_result and risk_result:
        forecast_units = forecast_result.get("forecast_units")
        recommended = replenishment_result.get("recommended_quantity")
        risk_level = risk_result.get("risk_level")
        if forecast_units is None or recommended is None or risk_level is None:
            raise ValueError(
                "forecast_result, replenishment_result, and risk_result must include "
                "forecast_units, recommended_quantity, and risk_level"
            )
        days_of_supply = replenishment_result.get("days_of_supply")
        raw_quantity = replenishment_result.get("raw_quantity", 0)
        case_pack = int(replenishment_result.get("case_pack", product.case_pack))
        average_daily_sales = forecast_result.get("average_daily_sales", 0)
        constraints = replenishment_result.get("constraints_applied") or []
        risk_reasons = risk_result.get("reasons") or []
        if not rationale:
            rationale = (
                f"Stored recommendation for {product.product_name}: "
                f"qty={recommended}, risk={risk_level}."
            )
    else:
        analysis = build_analysis(store_id, sku)
        forecast = analysis["forecast"]
        replenishment = analysis["replenishment"]
        risk = analysis["risk"]
        forecast_units = forecast.forecast_units
        recommended = replenishment.recommended_quantity
        risk_level = risk["risk_level"]
        days_of_supply = (
            float(replenishment.days_of_supply)
            if replenishment.days_of_supply is not None
            else None
        )
        raw_quantity = float(replenishment.raw_quantity)
        case_pack = replenishment.case_pack
        average_daily_sales = float(forecast.average_daily_sales)
        constraints = replenishment.constraints_applied
        risk_reasons = risk["reasons"]

    recommendation = Recommendation(
        recommendation_id=f"REC-{uuid4().hex[:12]}",
        store_id=store_id,
        sku=sku,
        forecast_units=forecast_units,
        available_units=inventory.usable_on_hand + inventory.in_transit,
        agent_recommended_quantity=int(recommended),
        risk_level=str(risk_level),
        rationale=rationale,
        created_at=datetime.now(timezone.utc),
        status="pending_review",
        user_id=user_id,
        session_id=session_id,
    )
    extras = {
        "product_name": product.product_name,
        "usable_on_hand": inventory.usable_on_hand,
        "in_transit": inventory.in_transit,
        "safety_stock": inventory.safety_stock,
        "days_of_supply": (
            float(days_of_supply) if days_of_supply is not None else None
        ),
        "raw_quantity": float(raw_quantity),
        "case_pack": case_pack,
        "average_daily_sales": float(average_daily_sales),
        "run_id": run_id,
        "constraints_applied": constraints,
        "risk_reasons": risk_reasons,
    }
    with get_session() as session:
        recommendation_repository.save_recommendation(session, recommendation, extras)
        audit_repository.write_audit_event(
            session,
            "recommendation_generated",
            actor=actor,
            run_id=run_id,
            recommendation_id=recommendation.recommendation_id,
            user_id=user_id,
            session_id=session_id,
            details={
                "store_id": store_id,
                "sku": sku,
                "agent_recommended_quantity": recommendation.agent_recommended_quantity,
                "risk_level": recommendation.risk_level,
            },
        )
    return recommendation


def get_recommendation(
    recommendation_id: str,
    *,
    user_id: str | None = None,
    role: str | None = None,
    check_access: bool = False,
) -> dict[str, Any]:
    with get_session() as session:
        recommendation = recommendation_repository.get_recommendation(session, recommendation_id)
        row = recommendation_repository.get_recommendation_row(session, recommendation_id)
        if recommendation is None or row is None:
            raise ValueError(f"Recommendation not found: {recommendation_id}")
        data = recommendation.model_dump(mode="json")
        data.update(
            {
                "product_name": row.product_name,
                "usable_on_hand": row.usable_on_hand,
                "in_transit": row.in_transit,
                "safety_stock": row.safety_stock,
                "days_of_supply": row.days_of_supply,
                "raw_quantity": row.raw_quantity,
                "case_pack": row.case_pack,
                "average_daily_sales": row.average_daily_sales,
                "run_id": row.run_id,
                "user_id": row.user_id,
                "session_id": row.session_id,
            }
        )
    if check_access:
        isolation_service.require_recommendation_access(data, user_id=user_id, role=role)
    return data


def list_recommendations_for_user(user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    with get_session() as session:
        rows = recommendation_repository.list_recent_recommendations(
            session, limit=limit, user_id=user_id
        )
        return [
            {
                "recommendation_id": row.recommendation_id,
                "store_id": row.store_id,
                "sku": row.sku,
                "status": row.status,
                "agent_recommended_quantity": row.agent_recommended_quantity,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]


def get_recommendation_history(
    store_id: str,
    sku: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Read-only history of saved recommendations for a store/SKU.

    Does not mutate records. Newest first.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    capped = min(int(limit), 50)
    product_service.get_product_details(sku)
    with get_session() as session:
        rows = recommendation_repository.list_recommendations_for_store_sku(
            session, store_id, sku, limit=capped
        )
        items = [
            {
                "recommendation_id": row.recommendation_id,
                "store_id": row.store_id,
                "sku": row.sku,
                "status": row.status,
                "agent_recommended_quantity": row.agent_recommended_quantity,
                "risk_level": row.risk_level,
                "forecast_units": row.forecast_units,
                "usable_on_hand": row.usable_on_hand,
                "in_transit": row.in_transit,
                "case_pack": row.case_pack,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "user_id": row.user_id,
                "session_id": row.session_id,
            }
            for row in rows
        ]
    return {
        "status": "ok",
        "store_id": store_id,
        "sku": sku,
        "limit": capped,
        "count": len(items),
        "recommendations": items,
    }

"""Recommendation persistence."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import RecommendationRow
from models.recommendation import Recommendation


def save_recommendation(session: Session, recommendation: Recommendation, extras: dict | None = None) -> Recommendation:
    extras = extras or {}
    row = session.get(RecommendationRow, recommendation.recommendation_id)
    payload = {
        "rationale": recommendation.rationale,
        **extras,
    }
    values = dict(
        store_id=recommendation.store_id,
        sku=recommendation.sku,
        forecast_units=float(recommendation.forecast_units),
        available_units=recommendation.available_units,
        agent_recommended_quantity=recommendation.agent_recommended_quantity,
        risk_level=recommendation.risk_level,
        rationale=recommendation.rationale,
        created_at=recommendation.created_at,
        status=recommendation.status,
        product_name=str(extras.get("product_name", "")),
        usable_on_hand=int(extras.get("usable_on_hand", 0)),
        in_transit=int(extras.get("in_transit", 0)),
        safety_stock=int(extras.get("safety_stock", 0)),
        days_of_supply=(
            float(extras["days_of_supply"]) if extras.get("days_of_supply") is not None else None
        ),
        raw_quantity=float(extras.get("raw_quantity", 0)),
        case_pack=int(extras.get("case_pack", 1)),
        average_daily_sales=float(extras.get("average_daily_sales", 0)),
        run_id=extras.get("run_id"),
        payload_json=json.dumps(payload, default=str),
    )
    if row is None:
        row = RecommendationRow(recommendation_id=recommendation.recommendation_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return recommendation


def get_recommendation(session: Session, recommendation_id: str) -> Recommendation | None:
    row = session.get(RecommendationRow, recommendation_id)
    if row is None:
        return None
    return Recommendation(
        recommendation_id=row.recommendation_id,
        store_id=row.store_id,
        sku=row.sku,
        forecast_units=Decimal(str(row.forecast_units)),
        available_units=row.available_units,
        agent_recommended_quantity=row.agent_recommended_quantity,
        risk_level=row.risk_level,
        rationale=row.rationale,
        created_at=row.created_at,
        status=row.status,
    )


def get_recommendation_row(session: Session, recommendation_id: str) -> RecommendationRow | None:
    return session.get(RecommendationRow, recommendation_id)


def update_recommendation_status(session: Session, recommendation_id: str, status: str) -> None:
    row = session.get(RecommendationRow, recommendation_id)
    if row is None:
        raise ValueError(f"Recommendation not found: {recommendation_id}")
    row.status = status
    session.flush()


def list_recent_recommendations(session: Session, limit: int = 20) -> list[RecommendationRow]:
    stmt = select(RecommendationRow).order_by(RecommendationRow.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))

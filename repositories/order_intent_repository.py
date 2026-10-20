"""Order intent persistence."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import OrderIntentRow
from models.order_intent import OrderIntent, OrderLine


def save_order_intent(session: Session, intent: OrderIntent) -> OrderIntent:
    row = session.get(OrderIntentRow, intent.order_intent_id)
    values = dict(
        recommendation_id=intent.recommendation_id,
        approval_id=intent.approval_id,
        purchase_order_id=intent.purchase_order_id,
        status=intent.status,
        store_id=intent.store_id,
        sku=intent.sku,
        product_name=intent.product_name,
        quantity=intent.quantity,
        unit_cost=intent.unit_cost,
        amount=intent.amount,
        vendor=intent.vendor,
        lines_json=json.dumps([line.model_dump(mode="json") for line in intent.lines], default=str),
        source_run_id=intent.source_run_id,
        approved_by=intent.approved_by,
        released_by_type=intent.released_by_type,
        released_by_label=intent.released_by_label,
        idempotency_key=intent.idempotency_key,
        transmission_idempotency_key=intent.transmission_idempotency_key,
        mock_erp_reference=intent.mock_erp_reference,
        external_order_id=intent.external_order_id,
        erp_provider=intent.erp_provider,
        transmitted_at=intent.transmitted_at,
        acknowledged_at=intent.acknowledged_at,
        last_error=intent.last_error,
        last_error_code=intent.last_error_code,
        last_error_message=intent.last_error_message,
        attempts=intent.attempts,
        last_attempt_at=intent.last_attempt_at,
        next_retry_at=intent.next_retry_at,
        execution_id=intent.execution_id,
        created_at=intent.created_at,
        updated_at=intent.updated_at,
        user_id=intent.user_id,
        session_id=intent.session_id,
        payload_json=json.dumps(intent.payload or {}, default=str),
    )
    if row is None:
        row = OrderIntentRow(order_intent_id=intent.order_intent_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return intent


def get_order_intent(session: Session, order_intent_id: str) -> OrderIntent | None:
    row = session.get(OrderIntentRow, order_intent_id)
    return _to_model(row) if row else None


def get_by_recommendation(session: Session, recommendation_id: str) -> OrderIntent | None:
    row = session.scalars(
        select(OrderIntentRow).where(OrderIntentRow.recommendation_id == recommendation_id)
    ).first()
    return _to_model(row) if row else None


def get_by_approval(session: Session, approval_id: str) -> OrderIntent | None:
    row = session.scalars(
        select(OrderIntentRow).where(OrderIntentRow.approval_id == approval_id)
    ).first()
    return _to_model(row) if row else None


def get_by_purchase_order(session: Session, purchase_order_id: str) -> OrderIntent | None:
    row = session.scalars(
        select(OrderIntentRow).where(
            OrderIntentRow.purchase_order_id == purchase_order_id
        )
    ).first()
    return _to_model(row) if row else None


def get_by_idempotency_key(session: Session, key: str) -> OrderIntent | None:
    row = session.scalars(
        select(OrderIntentRow).where(OrderIntentRow.idempotency_key == key)
    ).first()
    return _to_model(row) if row else None


def list_order_intents(
    session: Session,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[OrderIntent]:
    stmt = select(OrderIntentRow).order_by(OrderIntentRow.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(OrderIntentRow.status == status)
    return [_to_model(row) for row in session.scalars(stmt)]


def _to_model(row: OrderIntentRow) -> OrderIntent:
    try:
        lines_raw = json.loads(row.lines_json or "[]")
    except json.JSONDecodeError:
        lines_raw = []
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    lines = [OrderLine.model_validate(item) for item in lines_raw]
    return OrderIntent(
        order_intent_id=row.order_intent_id,
        recommendation_id=row.recommendation_id,
        approval_id=row.approval_id,
        purchase_order_id=row.purchase_order_id,
        status=row.status,  # type: ignore[arg-type]
        store_id=row.store_id,
        sku=row.sku,
        product_name=row.product_name,
        quantity=row.quantity,
        unit_cost=row.unit_cost,
        amount=row.amount,
        vendor=row.vendor,
        lines=lines,
        source_run_id=row.source_run_id,
        approved_by=row.approved_by,
        released_by_type=row.released_by_type,  # type: ignore[arg-type]
        released_by_label=row.released_by_label,
        idempotency_key=row.idempotency_key,
        transmission_idempotency_key=row.transmission_idempotency_key,
        mock_erp_reference=row.mock_erp_reference,
        external_order_id=row.external_order_id,
        erp_provider=row.erp_provider,
        transmitted_at=row.transmitted_at,
        acknowledged_at=row.acknowledged_at,
        last_error=row.last_error,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        attempts=row.attempts,
        last_attempt_at=row.last_attempt_at,
        next_retry_at=row.next_retry_at,
        execution_id=row.execution_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        user_id=row.user_id,
        session_id=row.session_id,
        payload=payload,
    )

"""Purchase order persistence."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import PurchaseOrderRow
from models.purchase_order import PurchaseOrder


def save_purchase_order(session: Session, purchase_order: PurchaseOrder) -> PurchaseOrder:
    idempotency_key = purchase_order.idempotency_key or purchase_order.approval_id

    existing = session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.approval_id == purchase_order.approval_id)
    ).first()
    if existing is not None:
        return _to_model(existing)

    by_key = session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.idempotency_key == idempotency_key)
    ).first()
    if by_key is not None:
        return _to_model(by_key)

    row = PurchaseOrderRow(
        purchase_order_id=purchase_order.purchase_order_id,
        approval_id=purchase_order.approval_id,
        recommendation_id=purchase_order.recommendation_id,
        store_id=purchase_order.store_id,
        sku=purchase_order.sku,
        agent_recommended_quantity=purchase_order.agent_recommended_quantity,
        human_proposed_quantity=purchase_order.human_proposed_quantity,
        approved_final_quantity=purchase_order.approved_final_quantity,
        override_used=purchase_order.override_used,
        override_reason=purchase_order.override_reason,
        status=purchase_order.status or "queued_for_erp",
        order_status=purchase_order.order_status or "queued_for_erp",
        transmission_status=purchase_order.transmission_status or "draft",
        transmitted_at=purchase_order.transmitted_at,
        acknowledged_at=purchase_order.acknowledged_at,
        erp_reference=purchase_order.erp_reference,
        external_order_id=purchase_order.external_order_id,
        erp_provider=purchase_order.erp_provider,
        transmission_error=purchase_order.transmission_error,
        last_error_code=purchase_order.last_error_code,
        attempt_count=purchase_order.attempt_count,
        transmission_idempotency_key=purchase_order.transmission_idempotency_key,
        last_attempt_at=purchase_order.last_attempt_at,
        next_retry_at=purchase_order.next_retry_at,
        vendor=purchase_order.vendor,
        amount=purchase_order.amount,
        lines_json=json.dumps(purchase_order.lines or [], default=str),
        source_run_id=purchase_order.source_run_id,
        approved_by=purchase_order.approved_by,
        created_at=purchase_order.created_at,
        idempotency_key=idempotency_key,
        user_id=purchase_order.user_id,
        session_id=purchase_order.session_id,
    )
    session.add(row)
    session.flush()
    return PurchaseOrder(
        **{**purchase_order.model_dump(), "idempotency_key": idempotency_key},
    )


def update_purchase_order(session: Session, purchase_order: PurchaseOrder) -> PurchaseOrder:
    row = session.get(PurchaseOrderRow, purchase_order.purchase_order_id)
    if row is None:
        raise ValueError(f"Purchase order not found: {purchase_order.purchase_order_id}")
    row.recommendation_id = purchase_order.recommendation_id
    row.status = purchase_order.status
    row.order_status = purchase_order.order_status
    row.transmission_status = purchase_order.transmission_status
    row.transmitted_at = purchase_order.transmitted_at
    row.acknowledged_at = purchase_order.acknowledged_at
    row.erp_reference = purchase_order.erp_reference
    row.external_order_id = purchase_order.external_order_id
    row.erp_provider = purchase_order.erp_provider
    row.transmission_error = purchase_order.transmission_error
    row.last_error_code = purchase_order.last_error_code
    row.attempt_count = purchase_order.attempt_count
    row.transmission_idempotency_key = purchase_order.transmission_idempotency_key
    row.last_attempt_at = purchase_order.last_attempt_at
    row.next_retry_at = purchase_order.next_retry_at
    row.vendor = purchase_order.vendor
    row.amount = purchase_order.amount
    row.lines_json = json.dumps(purchase_order.lines or [], default=str)
    row.source_run_id = purchase_order.source_run_id
    row.approved_by = purchase_order.approved_by
    session.flush()
    return _to_model(row)


def get_purchase_order(session: Session, purchase_order_id: str) -> PurchaseOrder | None:
    row = session.get(PurchaseOrderRow, purchase_order_id)
    return _to_model(row) if row else None


def get_purchase_order_by_approval(session: Session, approval_id: str) -> PurchaseOrder | None:
    row = session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.approval_id == approval_id)
    ).first()
    return _to_model(row) if row else None


def get_purchase_order_by_recommendation(
    session: Session, recommendation_id: str
) -> PurchaseOrder | None:
    row = session.scalars(
        select(PurchaseOrderRow).where(
            PurchaseOrderRow.recommendation_id == recommendation_id
        )
    ).first()
    return _to_model(row) if row else None


def get_purchase_order_by_idempotency_key(
    session: Session,
    idempotency_key: str,
) -> PurchaseOrder | None:
    row = session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.idempotency_key == idempotency_key)
    ).first()
    return _to_model(row) if row else None


def list_purchase_orders(
    session: Session,
    *,
    transmission_status: str | None = None,
    order_status: str | None = None,
    limit: int = 100,
) -> list[PurchaseOrder]:
    stmt = (
        select(PurchaseOrderRow)
        .order_by(PurchaseOrderRow.created_at.desc())
        .limit(limit)
    )
    if transmission_status is not None:
        stmt = stmt.where(PurchaseOrderRow.transmission_status == transmission_status)
    if order_status is not None:
        stmt = stmt.where(PurchaseOrderRow.order_status == order_status)
    return [_to_model(row) for row in session.scalars(stmt)]


def _to_model(row: PurchaseOrderRow) -> PurchaseOrder:
    try:
        lines = json.loads(getattr(row, "lines_json", None) or "[]")
    except json.JSONDecodeError:
        lines = []
    return PurchaseOrder(
        purchase_order_id=row.purchase_order_id,
        approval_id=row.approval_id,
        recommendation_id=row.recommendation_id,
        store_id=row.store_id,
        sku=row.sku,
        agent_recommended_quantity=row.agent_recommended_quantity,
        human_proposed_quantity=row.human_proposed_quantity,
        approved_final_quantity=row.approved_final_quantity,
        override_used=row.override_used,
        override_reason=row.override_reason,
        status=row.status,
        order_status=getattr(row, "order_status", None) or "queued_for_erp",
        transmission_status=getattr(row, "transmission_status", None) or "draft",
        transmitted_at=getattr(row, "transmitted_at", None),
        acknowledged_at=getattr(row, "acknowledged_at", None),
        erp_reference=getattr(row, "erp_reference", None),
        external_order_id=getattr(row, "external_order_id", None),
        erp_provider=getattr(row, "erp_provider", None),
        transmission_error=getattr(row, "transmission_error", None),
        last_error_code=getattr(row, "last_error_code", None),
        attempt_count=getattr(row, "attempt_count", 0) or 0,
        transmission_idempotency_key=getattr(row, "transmission_idempotency_key", None),
        last_attempt_at=getattr(row, "last_attempt_at", None),
        next_retry_at=getattr(row, "next_retry_at", None),
        vendor=getattr(row, "vendor", None),
        amount=getattr(row, "amount", None),
        lines=lines if isinstance(lines, list) else [],
        source_run_id=getattr(row, "source_run_id", None),
        approved_by=getattr(row, "approved_by", None),
        created_at=row.created_at,
        idempotency_key=row.idempotency_key,
        user_id=row.user_id,
        session_id=row.session_id,
    )

"""Purchase order persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import PurchaseOrderRow
from models.purchase_order import PurchaseOrder


def save_purchase_order(session: Session, purchase_order: PurchaseOrder) -> PurchaseOrder:
    existing = session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.approval_id == purchase_order.approval_id)
    ).first()
    if existing is not None:
        return _to_model(existing)

    row = PurchaseOrderRow(
        purchase_order_id=purchase_order.purchase_order_id,
        approval_id=purchase_order.approval_id,
        store_id=purchase_order.store_id,
        sku=purchase_order.sku,
        agent_recommended_quantity=purchase_order.agent_recommended_quantity,
        human_proposed_quantity=purchase_order.human_proposed_quantity,
        approved_final_quantity=purchase_order.approved_final_quantity,
        override_used=purchase_order.override_used,
        override_reason=purchase_order.override_reason,
        status=purchase_order.status,
        created_at=purchase_order.created_at,
    )
    session.add(row)
    session.flush()
    return purchase_order


def get_purchase_order(session: Session, purchase_order_id: str) -> PurchaseOrder | None:
    row = session.get(PurchaseOrderRow, purchase_order_id)
    return _to_model(row) if row else None


def get_purchase_order_by_approval(session: Session, approval_id: str) -> PurchaseOrder | None:
    row = session.scalars(
        select(PurchaseOrderRow).where(PurchaseOrderRow.approval_id == approval_id)
    ).first()
    return _to_model(row) if row else None


def _to_model(row: PurchaseOrderRow) -> PurchaseOrder:
    return PurchaseOrder(
        purchase_order_id=row.purchase_order_id,
        approval_id=row.approval_id,
        store_id=row.store_id,
        sku=row.sku,
        agent_recommended_quantity=row.agent_recommended_quantity,
        human_proposed_quantity=row.human_proposed_quantity,
        approved_final_quantity=row.approved_final_quantity,
        override_used=row.override_used,
        override_reason=row.override_reason,
        status=row.status,
        created_at=row.created_at,
    )

"""ERP outbox persistence."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ErpOutboxRow
from models.erp_outbox import ErpOutboxEntry


def save_outbox(session: Session, entry: ErpOutboxEntry) -> ErpOutboxEntry:
    row = session.get(ErpOutboxRow, entry.outbox_id)
    values = dict(
        purchase_order_id=entry.purchase_order_id,
        run_id=entry.run_id,
        batch_id=entry.batch_id,
        payload_json=json.dumps(entry.payload, default=str),
        status=entry.status,
        attempts=entry.attempts,
        last_error=entry.last_error,
        erp_reference=entry.erp_reference,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        sent_at=entry.sent_at,
    )
    if row is None:
        row = ErpOutboxRow(outbox_id=entry.outbox_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return entry


def get_outbox(session: Session, outbox_id: str) -> ErpOutboxEntry | None:
    row = session.get(ErpOutboxRow, outbox_id)
    return _to_model(row) if row else None


def get_outbox_by_purchase_order(
    session: Session, purchase_order_id: str
) -> ErpOutboxEntry | None:
    row = session.scalars(
        select(ErpOutboxRow).where(ErpOutboxRow.purchase_order_id == purchase_order_id)
    ).first()
    return _to_model(row) if row else None


def list_outbox(
    session: Session,
    *,
    status: str | None = None,
    batch_id: str | None = None,
    limit: int = 100,
) -> list[ErpOutboxEntry]:
    stmt = select(ErpOutboxRow).order_by(ErpOutboxRow.created_at.asc()).limit(limit)
    if status is not None:
        stmt = stmt.where(ErpOutboxRow.status == status)
    if batch_id is not None:
        stmt = stmt.where(ErpOutboxRow.batch_id == batch_id)
    return [_to_model(row) for row in session.scalars(stmt)]


def _to_model(row: ErpOutboxRow) -> ErpOutboxEntry:
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return ErpOutboxEntry(
        outbox_id=row.outbox_id,
        purchase_order_id=row.purchase_order_id,
        run_id=row.run_id,
        batch_id=row.batch_id,
        payload=payload,
        status=row.status,  # type: ignore[arg-type]
        attempts=row.attempts,
        last_error=row.last_error,
        erp_reference=row.erp_reference,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sent_at=row.sent_at,
    )

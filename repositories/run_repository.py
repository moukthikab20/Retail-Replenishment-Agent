"""Persistence for batch replenishment runs and per-item outcomes."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ReplenishmentRunItemRow, ReplenishmentRunRow, RecommendationRow
from models.replenishment_run import ReplenishmentRun, ReplenishmentRunItem


def _run_from_row(row: ReplenishmentRunRow) -> ReplenishmentRun:
    return ReplenishmentRun(
        run_id=row.run_id,
        started_at=row.started_at,
        completed_at=row.completed_at,
        status=row.status,  # type: ignore[arg-type]
        trigger_type=row.trigger_type,  # type: ignore[arg-type]
        initiated_by=row.initiated_by,
        total_items=row.total_items,
        scored_items=row.scored_items,
        auto_released_items=row.auto_released_items,
        review_items=row.review_items,
        blocked_items=row.blocked_items,
        no_order_items=int(getattr(row, "no_order_items", 0) or 0),
        failed_items=row.failed_items,
        policy_version=row.policy_version,
        model_name=row.model_name,
        error_summary=row.error_summary,
        created_at=row.created_at,
        invocation_key=getattr(row, "invocation_key", None),
        scheduled_for=getattr(row, "scheduled_for", None),
    )


def _item_from_row(row: ReplenishmentRunItemRow) -> ReplenishmentRunItem:
    return ReplenishmentRunItem(
        item_id=row.item_id,
        run_id=row.run_id,
        store_id=row.store_id,
        sku=row.sku,
        status=row.status,  # type: ignore[arg-type]
        disposition=row.disposition,  # type: ignore[arg-type]
        recommendation_id=row.recommendation_id,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def save_run(session: Session, run: ReplenishmentRun) -> ReplenishmentRun:
    row = session.get(ReplenishmentRunRow, run.run_id)
    values = dict(
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        trigger_type=run.trigger_type,
        initiated_by=run.initiated_by,
        total_items=run.total_items,
        scored_items=run.scored_items,
        auto_released_items=run.auto_released_items,
        review_items=run.review_items,
        blocked_items=run.blocked_items,
        no_order_items=run.no_order_items,
        failed_items=run.failed_items,
        policy_version=run.policy_version,
        model_name=run.model_name,
        error_summary=run.error_summary,
        created_at=run.created_at,
        invocation_key=run.invocation_key,
        scheduled_for=run.scheduled_for,
    )
    if row is None:
        row = ReplenishmentRunRow(run_id=run.run_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return run


def get_run(session: Session, run_id: str) -> ReplenishmentRun | None:
    row = session.get(ReplenishmentRunRow, run_id)
    if row is None:
        return None
    return _run_from_row(row)


def get_run_by_invocation_key(
    session: Session, invocation_key: str
) -> ReplenishmentRun | None:
    if not invocation_key:
        return None
    stmt = select(ReplenishmentRunRow).where(
        ReplenishmentRunRow.invocation_key == invocation_key
    )
    row = session.scalars(stmt).first()
    return None if row is None else _run_from_row(row)


def get_latest_scheduled_run(
    session: Session,
    *,
    successful_only: bool = False,
) -> ReplenishmentRun | None:
    stmt = (
        select(ReplenishmentRunRow)
        .where(ReplenishmentRunRow.trigger_type == "scheduled")
        .order_by(
            ReplenishmentRunRow.created_at.desc(),
            ReplenishmentRunRow.run_id.desc(),
        )
    )
    if successful_only:
        stmt = stmt.where(
            ReplenishmentRunRow.status.in_(("completed", "completed_with_errors"))
        )
    row = session.scalars(stmt).first()
    return None if row is None else _run_from_row(row)


def list_run_items(session: Session, run_id: str) -> list[ReplenishmentRunItem]:
    stmt = (
        select(ReplenishmentRunItemRow)
        .where(ReplenishmentRunItemRow.run_id == run_id)
        .order_by(ReplenishmentRunItemRow.created_at.asc())
    )
    return [_item_from_row(row) for row in session.scalars(stmt)]


def get_run_item(
    session: Session,
    *,
    run_id: str,
    store_id: str,
    sku: str,
) -> ReplenishmentRunItem | None:
    stmt = select(ReplenishmentRunItemRow).where(
        ReplenishmentRunItemRow.run_id == run_id,
        ReplenishmentRunItemRow.store_id == store_id,
        ReplenishmentRunItemRow.sku == sku,
    )
    row = session.scalars(stmt).first()
    if row is None:
        return None
    return _item_from_row(row)


def save_run_item(session: Session, item: ReplenishmentRunItem) -> ReplenishmentRunItem:
    row = session.get(ReplenishmentRunItemRow, item.item_id)
    values = dict(
        run_id=item.run_id,
        store_id=item.store_id,
        sku=item.sku,
        status=item.status,
        disposition=item.disposition,
        recommendation_id=item.recommendation_id,
        error_message=item.error_message,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
    if row is None:
        existing = get_run_item(
            session, run_id=item.run_id, store_id=item.store_id, sku=item.sku
        )
        if existing is not None:
            row = session.get(ReplenishmentRunItemRow, existing.item_id)
        if row is None:
            row = ReplenishmentRunItemRow(item_id=item.item_id, **values)
            session.add(row)
        else:
            for key, value in values.items():
                if key != "created_at":
                    setattr(row, key, value)
    else:
        for key, value in values.items():
            if key != "created_at":
                setattr(row, key, value)
    session.flush()
    return item


def get_recommendation_for_run_item(
    session: Session,
    *,
    run_id: str,
    store_id: str,
    sku: str,
) -> RecommendationRow | None:
    stmt = select(RecommendationRow).where(
        RecommendationRow.run_id == run_id,
        RecommendationRow.store_id == store_id,
        RecommendationRow.sku == sku,
    )
    return session.scalars(stmt).first()


def get_latest_run(
    session: Session,
    *,
    terminal_only: bool = True,
) -> ReplenishmentRun | None:
    """Return the most recent replenishment run (prefer completed statuses)."""
    stmt = select(ReplenishmentRunRow).order_by(
        ReplenishmentRunRow.created_at.desc(),
        ReplenishmentRunRow.run_id.desc(),
    )
    if terminal_only:
        stmt = stmt.where(
            ReplenishmentRunRow.status.in_(
                ("completed", "completed_with_errors", "failed")
            )
        )
    row = session.scalars(stmt).first()
    if row is None and terminal_only:
        # Fall back to any latest run if none are terminal yet.
        row = session.scalars(
            select(ReplenishmentRunRow).order_by(
                ReplenishmentRunRow.created_at.desc(),
                ReplenishmentRunRow.run_id.desc(),
            )
        ).first()
    return None if row is None else _run_from_row(row)


def get_active_run(session: Session) -> ReplenishmentRun | None:
    """Return an in-progress run if one exists (pending or running)."""
    stmt = (
        select(ReplenishmentRunRow)
        .where(ReplenishmentRunRow.status.in_(("pending", "running")))
        .order_by(
            ReplenishmentRunRow.created_at.desc(),
            ReplenishmentRunRow.run_id.desc(),
        )
        .limit(1)
    )
    row = session.scalars(stmt).first()
    return None if row is None else _run_from_row(row)


def list_runs(
    session: Session,
    *,
    limit: int = 50,
    terminal_only: bool = False,
) -> list[ReplenishmentRun]:
    """Newest-first replenishment runs for the Ops Center selector."""
    stmt = select(ReplenishmentRunRow).order_by(
        ReplenishmentRunRow.created_at.desc(),
        ReplenishmentRunRow.run_id.desc(),
    )
    if terminal_only:
        stmt = stmt.where(
            ReplenishmentRunRow.status.in_(
                ("completed", "completed_with_errors", "failed")
            )
        )
    stmt = stmt.limit(max(1, min(int(limit), 200)))
    return [_run_from_row(row) for row in session.scalars(stmt)]


def list_recommendations_for_run(
    session: Session,
    run_id: str,
) -> list[RecommendationRow]:
    stmt = (
        select(RecommendationRow)
        .where(RecommendationRow.run_id == run_id)
        .order_by(RecommendationRow.created_at.asc())
    )
    return list(session.scalars(stmt))


def touch_run_item_timestamp(item: ReplenishmentRunItem, when: datetime) -> ReplenishmentRunItem:
    return item.model_copy(update={"updated_at": when})

"""Approval persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ApprovalRow
from models.approval import ApprovalRequest


def save_approval(session: Session, approval: ApprovalRequest) -> ApprovalRequest:
    row = session.get(ApprovalRow, approval.approval_id)
    values = dict(
        review_id=approval.review_id,
        recommendation_id=approval.recommendation_id,
        agent_recommended_quantity=approval.agent_recommended_quantity,
        human_proposed_quantity=approval.human_proposed_quantity,
        approved_final_quantity=approval.approved_final_quantity,
        required_role=approval.required_role,
        status=approval.status,
        requested_at=approval.requested_at,
        approved_by=approval.approved_by,
        approved_at=approval.approved_at,
        rejection_reason=approval.rejection_reason,
    )
    if row is None:
        row = ApprovalRow(approval_id=approval.approval_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return approval


def get_approval(session: Session, approval_id: str) -> ApprovalRequest | None:
    row = session.get(ApprovalRow, approval_id)
    if row is None:
        return None
    return _to_model(row)


def get_latest_approval_for_review(session: Session, review_id: str) -> ApprovalRequest | None:
    stmt = (
        select(ApprovalRow)
        .where(ApprovalRow.review_id == review_id)
        .order_by(ApprovalRow.requested_at.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    return _to_model(row) if row else None


def _to_model(row: ApprovalRow) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=row.approval_id,
        review_id=row.review_id,
        recommendation_id=row.recommendation_id,
        agent_recommended_quantity=row.agent_recommended_quantity,
        human_proposed_quantity=row.human_proposed_quantity,
        approved_final_quantity=row.approved_final_quantity,
        required_role=row.required_role,
        status=row.status,
        requested_at=row.requested_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        rejection_reason=row.rejection_reason,
    )

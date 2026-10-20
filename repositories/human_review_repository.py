"""Human review persistence."""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import HumanReviewRow
from models.human_review import HumanReplenishmentReview


def save_human_review(session: Session, review: HumanReplenishmentReview) -> HumanReplenishmentReview:
    row = session.get(HumanReviewRow, review.review_id)
    values = dict(
        recommendation_id=review.recommendation_id,
        agent_recommended_quantity=review.agent_recommended_quantity,
        human_proposed_quantity=review.human_proposed_quantity,
        override_used=review.override_used,
        override_reason=review.override_reason,
        reason_code=review.reason_code,
        comments=review.comments,
        decision_action=review.decision_action,
        quantity_source=review.quantity_source or "agent",
        ai_recommendation_unavailable=bool(review.ai_recommendation_unavailable),
        difference_units=review.difference_units,
        difference_percent=float(review.difference_percent),
        projected_days_of_supply=(
            float(review.projected_days_of_supply)
            if review.projected_days_of_supply is not None
            else None
        ),
        projected_risk=review.projected_risk,
        requires_escalation=review.requires_escalation,
        submitted_by=review.submitted_by,
        submitted_at=review.submitted_at,
        status=review.status,
        approval_level=review.approval_level,
        validation_messages_json=json.dumps(review.validation_messages),
        case_pack_compliant=review.case_pack_compliant,
        nearest_lower_case_pack=review.nearest_lower_case_pack,
        nearest_higher_case_pack=review.nearest_higher_case_pack,
        user_id=review.user_id,
        session_id=review.session_id,
    )
    if row is None:
        row = HumanReviewRow(review_id=review.review_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return review


def get_human_review(session: Session, review_id: str) -> HumanReplenishmentReview | None:
    row = session.get(HumanReviewRow, review_id)
    if row is None:
        return None
    return _to_model(row)


def get_latest_review_for_recommendation(
    session: Session,
    recommendation_id: str,
) -> HumanReplenishmentReview | None:
    stmt = (
        select(HumanReviewRow)
        .where(HumanReviewRow.recommendation_id == recommendation_id)
        .order_by(HumanReviewRow.submitted_at.desc())
        .limit(1)
    )
    row = session.scalars(stmt).first()
    return _to_model(row) if row else None


def _to_model(row: HumanReviewRow) -> HumanReplenishmentReview:
    return HumanReplenishmentReview(
        review_id=row.review_id,
        recommendation_id=row.recommendation_id,
        agent_recommended_quantity=row.agent_recommended_quantity,
        human_proposed_quantity=row.human_proposed_quantity,
        override_used=row.override_used,
        override_reason=row.override_reason,
        reason_code=getattr(row, "reason_code", None),
        comments=getattr(row, "comments", None),
        decision_action=getattr(row, "decision_action", None),
        quantity_source=getattr(row, "quantity_source", None) or "agent",
        ai_recommendation_unavailable=bool(
            getattr(row, "ai_recommendation_unavailable", False)
        ),
        difference_units=row.difference_units,
        difference_percent=Decimal(str(row.difference_percent)),
        projected_days_of_supply=(
            Decimal(str(row.projected_days_of_supply))
            if row.projected_days_of_supply is not None
            else None
        ),
        projected_risk=row.projected_risk,
        requires_escalation=row.requires_escalation,
        submitted_by=row.submitted_by,
        submitted_at=row.submitted_at,
        status=row.status,
        approval_level=row.approval_level,
        validation_messages=json.loads(row.validation_messages_json or "[]"),
        case_pack_compliant=row.case_pack_compliant,
        nearest_lower_case_pack=row.nearest_lower_case_pack,
        nearest_higher_case_pack=row.nearest_higher_case_pack,
        user_id=row.user_id,
        session_id=row.session_id,
    )

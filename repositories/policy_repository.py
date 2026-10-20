"""Persistence for versioned replenishment policy configs."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import PolicyConfigRow
from models.policy import PolicyConfig


def _from_row(row: PolicyConfigRow) -> PolicyConfig:
    return PolicyConfig(
        policy_id=row.policy_id,
        policy_version=row.policy_version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        active=row.active,
        auto_release_max_value=Decimal(str(row.auto_release_max_value)),
        minimum_confidence=Decimal(str(row.minimum_confidence)),
        maximum_inventory_age_hours=row.maximum_inventory_age_hours,
        maximum_days_of_supply=Decimal(str(row.maximum_days_of_supply)),
        minimum_history_days=row.minimum_history_days,
        require_review_for_stockout=row.require_review_for_stockout,
        require_review_for_overstock=row.require_review_for_overstock,
        require_review_for_promotion_overlap=row.require_review_for_promotion_overlap,
        maximum_override_percent=Decimal(str(row.maximum_override_percent)),
        require_formal_approval_above_value=Decimal(
            str(row.require_formal_approval_above_value)
        ),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def save_policy(session: Session, policy: PolicyConfig) -> PolicyConfig:
    row = session.get(PolicyConfigRow, policy.policy_id)
    values = dict(
        policy_version=policy.policy_version,
        effective_from=policy.effective_from,
        effective_to=policy.effective_to,
        active=policy.active,
        auto_release_max_value=float(policy.auto_release_max_value),
        minimum_confidence=float(policy.minimum_confidence),
        maximum_inventory_age_hours=policy.maximum_inventory_age_hours,
        maximum_days_of_supply=float(policy.maximum_days_of_supply),
        minimum_history_days=policy.minimum_history_days,
        require_review_for_stockout=policy.require_review_for_stockout,
        require_review_for_overstock=policy.require_review_for_overstock,
        require_review_for_promotion_overlap=policy.require_review_for_promotion_overlap,
        maximum_override_percent=float(policy.maximum_override_percent),
        require_formal_approval_above_value=float(
            policy.require_formal_approval_above_value
        ),
        created_by=policy.created_by,
        created_at=policy.created_at,
    )
    if row is None:
        row = PolicyConfigRow(policy_id=policy.policy_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return policy


def get_policy(session: Session, policy_id: str) -> PolicyConfig | None:
    row = session.get(PolicyConfigRow, policy_id)
    return None if row is None else _from_row(row)


def get_policy_by_version(session: Session, policy_version: str) -> PolicyConfig | None:
    stmt = select(PolicyConfigRow).where(PolicyConfigRow.policy_version == policy_version)
    row = session.scalars(stmt).first()
    return None if row is None else _from_row(row)


def get_active_policy(session: Session) -> PolicyConfig | None:
    stmt = (
        select(PolicyConfigRow)
        .where(PolicyConfigRow.active.is_(True))
        .order_by(PolicyConfigRow.effective_from.desc())
    )
    row = session.scalars(stmt).first()
    return None if row is None else _from_row(row)


def list_policies(session: Session, *, limit: int = 50) -> list[PolicyConfig]:
    stmt = (
        select(PolicyConfigRow)
        .order_by(
            PolicyConfigRow.active.desc(),
            PolicyConfigRow.effective_from.desc(),
            PolicyConfigRow.created_at.desc(),
        )
        .limit(limit)
    )
    return [_from_row(row) for row in session.scalars(stmt)]

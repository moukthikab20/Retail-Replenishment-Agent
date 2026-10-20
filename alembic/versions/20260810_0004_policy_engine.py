"""Add policy_configs and per-recommendation policy evaluation storage.

Revision ID: 20260810_0004
Revises: 20260810_0003
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0004"
down_revision: str | None = "20260810_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_configs",
        sa.Column("policy_id", sa.String(length=64), primary_key=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("auto_release_max_value", sa.Float(), nullable=False),
        sa.Column("minimum_confidence", sa.Float(), nullable=False),
        sa.Column("maximum_inventory_age_hours", sa.Integer(), nullable=False),
        sa.Column("maximum_days_of_supply", sa.Float(), nullable=False),
        sa.Column("minimum_history_days", sa.Integer(), nullable=False),
        sa.Column("require_review_for_stockout", sa.Boolean(), nullable=False),
        sa.Column("require_review_for_overstock", sa.Boolean(), nullable=False),
        sa.Column("require_review_for_promotion_overlap", sa.Boolean(), nullable=False),
        sa.Column("maximum_override_percent", sa.Float(), nullable=False),
        sa.Column("require_formal_approval_above_value", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("policy_version", name="uq_policy_configs_version"),
    )

    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.add_column(sa.Column("policy_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("policy_version", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "policy_evaluation_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_column("policy_evaluation_json")
        batch_op.drop_column("policy_version")
        batch_op.drop_column("policy_id")
    op.drop_table("policy_configs")

"""Add replenishment_runs, run_items, and recommendation disposition.

Revision ID: 20260810_0003
Revises: 20260804_0002
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0003"
down_revision: str | None = "20260804_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replenishment_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("initiated_by", sa.String(length=128), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("scored_items", sa.Integer(), nullable=False),
        sa.Column("auto_released_items", sa.Integer(), nullable=False),
        sa.Column("review_items", sa.Integer(), nullable=False),
        sa.Column("blocked_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "replenishment_run_items",
        sa.Column("item_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("store_id", sa.String(length=32), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=True),
        sa.Column("recommendation_id", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "store_id",
            "sku",
            name="uq_run_item_run_store_sku",
        ),
    )
    op.create_index(
        "ix_replenishment_run_items_run_id",
        "replenishment_run_items",
        ["run_id"],
    )
    op.create_index(
        "ix_replenishment_run_items_recommendation_id",
        "replenishment_run_items",
        ["recommendation_id"],
    )

    # SQLite cannot ALTER ADD CONSTRAINT; use batch mode for cross-dialect safety.
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.add_column(
            sa.Column("disposition", sa.String(length=32), nullable=True)
        )
        batch_op.create_index(
            "ix_recommendations_disposition",
            ["disposition"],
        )
        batch_op.create_index(
            "ix_recommendations_run_id",
            ["run_id"],
        )
        batch_op.create_unique_constraint(
            "uq_recommendation_run_store_sku",
            ["run_id", "store_id", "sku"],
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch_op:
        batch_op.drop_constraint(
            "uq_recommendation_run_store_sku",
            type_="unique",
        )
        batch_op.drop_index("ix_recommendations_run_id")
        batch_op.drop_index("ix_recommendations_disposition")
        batch_op.drop_column("disposition")
    op.drop_table("replenishment_run_items")
    op.drop_table("replenishment_runs")

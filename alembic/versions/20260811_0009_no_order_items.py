"""Persist no_order_items on replenishment_runs.

Revision ID: 20260811_0009
Revises: 20260810_0008
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0009"
down_revision: str | None = "20260810_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("replenishment_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "no_order_items",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("replenishment_runs") as batch_op:
        batch_op.drop_column("no_order_items")

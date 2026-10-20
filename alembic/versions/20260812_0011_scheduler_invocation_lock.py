"""Add replenishment run invocation_key and scheduler_locks.

Revision ID: 20260812_0011
Revises: 20260811_0010
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0011"
down_revision: str | None = "20260811_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("replenishment_runs") as batch_op:
        batch_op.add_column(sa.Column("invocation_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("scheduled_for", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "uq_replenishment_runs_invocation_key",
            ["invocation_key"],
            unique=True,
        )

    op.create_table(
        "scheduler_locks",
        sa.Column("lock_name", sa.String(length=64), primary_key=True),
        sa.Column("holder", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scheduler_locks")
    with op.batch_alter_table("replenishment_runs") as batch_op:
        batch_op.drop_index("uq_replenishment_runs_invocation_key")
        batch_op.drop_column("scheduled_for")
        batch_op.drop_column("invocation_key")

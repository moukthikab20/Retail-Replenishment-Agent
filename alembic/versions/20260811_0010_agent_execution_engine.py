"""Extend agent_run_states into durable execution records.

Revision ID: 20260811_0010
Revises: 20260811_0009
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0010"
down_revision: str | None = "20260811_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_run_states") as batch_op:
        batch_op.add_column(sa.Column("execution_type", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("current_step", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("next_action", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
        )
        batch_op.add_column(sa.Column("waiting_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_error_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("correlation_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_agent_run_states_execution_type", ["execution_type"], unique=False
        )
        batch_op.create_index(
            "ix_agent_run_states_correlation_id", ["correlation_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_run_states") as batch_op:
        batch_op.drop_index("ix_agent_run_states_correlation_id")
        batch_op.drop_index("ix_agent_run_states_execution_type")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("version")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("last_error_message")
        batch_op.drop_column("last_error_code")
        batch_op.drop_column("waiting_reason")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("next_action")
        batch_op.drop_column("current_step")
        batch_op.drop_column("execution_type")

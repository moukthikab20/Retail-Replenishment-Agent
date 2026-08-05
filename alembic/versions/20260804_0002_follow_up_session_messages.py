"""Add agent_follow_up_messages for durable follow-up conversation memory.

Revision ID: 20260804_0002
Revises: 20260731_0001
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0002"
down_revision: str | None = "20260731_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_follow_up_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_key", sa.String(length=256), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("recommendation_id", sa.String(length=64), nullable=False),
        sa.Column("item_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_agent_follow_up_messages_session_key",
        "agent_follow_up_messages",
        ["session_key"],
    )
    op.create_index(
        "ix_agent_follow_up_messages_user_id",
        "agent_follow_up_messages",
        ["user_id"],
    )
    op.create_index(
        "ix_agent_follow_up_messages_recommendation_id",
        "agent_follow_up_messages",
        ["recommendation_id"],
    )


def downgrade() -> None:
    op.drop_table("agent_follow_up_messages")

"""Human decision workflow fields on recommendations and reviews.

Revision ID: 20260810_0006
Revises: 20260810_0005
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0006"
down_revision: str | None = "20260810_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("recommendation_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("recommendations", sa.Column("declined_by", sa.String(length=128), nullable=True))
    op.add_column("recommendations", sa.Column("declined_role", sa.String(length=64), nullable=True))
    op.add_column("recommendations", sa.Column("declined_at", sa.DateTime(), nullable=True))
    op.add_column("recommendations", sa.Column("decline_reason", sa.Text(), nullable=True))
    op.add_column(
        "recommendations",
        sa.Column("decline_reason_code", sa.String(length=64), nullable=True),
    )

    op.add_column("human_reviews", sa.Column("reason_code", sa.String(length=64), nullable=True))
    op.add_column("human_reviews", sa.Column("comments", sa.Text(), nullable=True))
    op.add_column(
        "human_reviews", sa.Column("decision_action", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "human_reviews",
        sa.Column("quantity_source", sa.String(length=32), nullable=False, server_default="agent"),
    )
    op.add_column(
        "human_reviews",
        sa.Column(
            "ai_recommendation_unavailable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("human_reviews", "ai_recommendation_unavailable")
    op.drop_column("human_reviews", "quantity_source")
    op.drop_column("human_reviews", "decision_action")
    op.drop_column("human_reviews", "comments")
    op.drop_column("human_reviews", "reason_code")
    op.drop_column("recommendations", "decline_reason_code")
    op.drop_column("recommendations", "decline_reason")
    op.drop_column("recommendations", "declined_at")
    op.drop_column("recommendations", "declined_role")
    op.drop_column("recommendations", "declined_by")
    op.drop_column("recommendations", "recommendation_version")

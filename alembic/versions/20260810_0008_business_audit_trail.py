"""Expand audit_events for unified business audit trail.

Revision ID: 20260810_0008
Revises: 20260810_0007
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0008"
down_revision: str | None = "20260810_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("actor_type", sa.String(length=32), nullable=True))
    op.add_column("audit_events", sa.Column("actor_id", sa.String(length=128), nullable=True))
    op.add_column("audit_events", sa.Column("store_id", sa.String(length=32), nullable=True))
    op.add_column("audit_events", sa.Column("sku", sa.String(length=64), nullable=True))
    op.add_column(
        "audit_events", sa.Column("correlation_id", sa.String(length=64), nullable=True)
    )
    op.create_index("ix_audit_events_actor_type", "audit_events", ["actor_type"])
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_store_id", "audit_events", ["store_id"])
    op.create_index("ix_audit_events_sku", "audit_events", ["sku"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_sku", table_name="audit_events")
    op.drop_index("ix_audit_events_store_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_type", table_name="audit_events")
    op.drop_column("audit_events", "correlation_id")
    op.drop_column("audit_events", "sku")
    op.drop_column("audit_events", "store_id")
    op.drop_column("audit_events", "actor_id")
    op.drop_column("audit_events", "actor_type")

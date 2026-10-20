"""Add ERP outbox and purchase-order transmission fields.

Revision ID: 20260810_0005
Revises: 20260810_0004
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0005"
down_revision: str | None = "20260810_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("recommendation_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "transmission_status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("transmitted_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("erp_reference", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("transmission_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_purchase_orders_recommendation_id",
        "purchase_orders",
        ["recommendation_id"],
    )
    op.create_index(
        "ix_purchase_orders_transmission_status",
        "purchase_orders",
        ["transmission_status"],
    )

    op.create_table(
        "erp_outbox",
        sa.Column("outbox_id", sa.String(length=64), primary_key=True),
        sa.Column("purchase_order_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("erp_reference", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("purchase_order_id", name="uq_erp_outbox_purchase_order_id"),
    )
    op.create_index("ix_erp_outbox_purchase_order_id", "erp_outbox", ["purchase_order_id"])
    op.create_index("ix_erp_outbox_run_id", "erp_outbox", ["run_id"])
    op.create_index("ix_erp_outbox_batch_id", "erp_outbox", ["batch_id"])
    op.create_index("ix_erp_outbox_status", "erp_outbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_erp_outbox_status", table_name="erp_outbox")
    op.drop_index("ix_erp_outbox_batch_id", table_name="erp_outbox")
    op.drop_index("ix_erp_outbox_run_id", table_name="erp_outbox")
    op.drop_index("ix_erp_outbox_purchase_order_id", table_name="erp_outbox")
    op.drop_table("erp_outbox")
    op.drop_index("ix_purchase_orders_transmission_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_recommendation_id", table_name="purchase_orders")
    op.drop_column("purchase_orders", "transmission_error")
    op.drop_column("purchase_orders", "erp_reference")
    op.drop_column("purchase_orders", "transmitted_at")
    op.drop_column("purchase_orders", "transmission_status")
    op.drop_column("purchase_orders", "recommendation_id")

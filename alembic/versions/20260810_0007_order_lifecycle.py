"""Add order_intents and purchase-order lifecycle fields.

Revision ID: 20260810_0007
Revises: 20260810_0006
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0007"
down_revision: str | None = "20260810_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("order_status", sa.String(length=32), nullable=False, server_default="pending_erp"),
    )
    op.add_column("purchase_orders", sa.Column("vendor", sa.String(length=128), nullable=True))
    op.add_column("purchase_orders", sa.Column("amount", sa.Float(), nullable=True))
    op.add_column(
        "purchase_orders",
        sa.Column("lines_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("purchase_orders", sa.Column("source_run_id", sa.String(length=64), nullable=True))
    op.add_column("purchase_orders", sa.Column("approved_by", sa.String(length=128), nullable=True))
    op.create_index("ix_purchase_orders_order_status", "purchase_orders", ["order_status"])
    op.create_index("ix_purchase_orders_source_run_id", "purchase_orders", ["source_run_id"])

    op.create_table(
        "order_intents",
        sa.Column("order_intent_id", sa.String(length=64), primary_key=True),
        sa.Column("recommendation_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("purchase_order_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("store_id", sa.String(length=32), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Float(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=False),
        sa.Column("lines_json", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.String(length=64), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("released_by_type", sa.String(length=32), nullable=False),
        sa.Column("released_by_label", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("mock_erp_reference", sa.String(length=128), nullable=True),
        sa.Column("transmitted_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("recommendation_id", name="uq_order_intent_recommendation_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_order_intent_idempotency_key"),
    )
    op.create_index("ix_order_intents_recommendation_id", "order_intents", ["recommendation_id"])
    op.create_index("ix_order_intents_approval_id", "order_intents", ["approval_id"])
    op.create_index("ix_order_intents_purchase_order_id", "order_intents", ["purchase_order_id"])
    op.create_index("ix_order_intents_status", "order_intents", ["status"])
    op.create_index("ix_order_intents_source_run_id", "order_intents", ["source_run_id"])
    op.create_index("ix_order_intents_user_id", "order_intents", ["user_id"])
    op.create_index("ix_order_intents_session_id", "order_intents", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_order_intents_session_id", table_name="order_intents")
    op.drop_index("ix_order_intents_user_id", table_name="order_intents")
    op.drop_index("ix_order_intents_source_run_id", table_name="order_intents")
    op.drop_index("ix_order_intents_status", table_name="order_intents")
    op.drop_index("ix_order_intents_purchase_order_id", table_name="order_intents")
    op.drop_index("ix_order_intents_approval_id", table_name="order_intents")
    op.drop_index("ix_order_intents_recommendation_id", table_name="order_intents")
    op.drop_table("order_intents")
    op.drop_index("ix_purchase_orders_source_run_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_order_status", table_name="purchase_orders")
    op.drop_column("purchase_orders", "approved_by")
    op.drop_column("purchase_orders", "source_run_id")
    op.drop_column("purchase_orders", "lines_json")
    op.drop_column("purchase_orders", "amount")
    op.drop_column("purchase_orders", "vendor")
    op.drop_column("purchase_orders", "order_status")

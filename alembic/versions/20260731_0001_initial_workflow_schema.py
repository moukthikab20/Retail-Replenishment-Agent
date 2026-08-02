"""Initial workflow schema with ownership and uniqueness constraints.

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("recommendation_id", sa.String(length=64), primary_key=True),
        sa.Column("store_id", sa.String(length=32), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("forecast_units", sa.Float(), nullable=False),
        sa.Column("available_units", sa.Integer(), nullable=False),
        sa.Column("agent_recommended_quantity", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("usable_on_hand", sa.Integer(), nullable=False),
        sa.Column("in_transit", sa.Integer(), nullable=False),
        sa.Column("safety_stock", sa.Integer(), nullable=False),
        sa.Column("days_of_supply", sa.Float(), nullable=True),
        sa.Column("raw_quantity", sa.Float(), nullable=False),
        sa.Column("case_pack", sa.Integer(), nullable=False),
        sa.Column("average_daily_sales", sa.Float(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_recommendations_store_id", "recommendations", ["store_id"])
    op.create_index("ix_recommendations_sku", "recommendations", ["sku"])
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_index("ix_recommendations_session_id", "recommendations", ["session_id"])

    op.create_table(
        "human_reviews",
        sa.Column("review_id", sa.String(length=64), primary_key=True),
        sa.Column("recommendation_id", sa.String(length=64), nullable=False),
        sa.Column("agent_recommended_quantity", sa.Integer(), nullable=False),
        sa.Column("human_proposed_quantity", sa.Integer(), nullable=False),
        sa.Column("override_used", sa.Boolean(), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("difference_units", sa.Integer(), nullable=False),
        sa.Column("difference_percent", sa.Float(), nullable=False),
        sa.Column("projected_days_of_supply", sa.Float(), nullable=True),
        sa.Column("projected_risk", sa.String(length=32), nullable=False),
        sa.Column("requires_escalation", sa.Boolean(), nullable=False),
        sa.Column("submitted_by", sa.String(length=128), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_level", sa.String(length=32), nullable=False),
        sa.Column("validation_messages_json", sa.Text(), nullable=False),
        sa.Column("case_pack_compliant", sa.Boolean(), nullable=False),
        sa.Column("nearest_lower_case_pack", sa.Integer(), nullable=True),
        sa.Column("nearest_higher_case_pack", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_human_reviews_recommendation_id", "human_reviews", ["recommendation_id"])
    op.create_index("ix_human_reviews_user_id", "human_reviews", ["user_id"])
    op.create_index("ix_human_reviews_session_id", "human_reviews", ["session_id"])

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=64), primary_key=True),
        sa.Column("review_id", sa.String(length=64), nullable=False),
        sa.Column("recommendation_id", sa.String(length=64), nullable=False),
        sa.Column("agent_recommended_quantity", sa.Integer(), nullable=False),
        sa.Column("human_proposed_quantity", sa.Integer(), nullable=False),
        sa.Column("approved_final_quantity", sa.Integer(), nullable=True),
        sa.Column("required_role", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("review_id", name="uq_approval_review_id"),
    )
    op.create_index("ix_approvals_review_id", "approvals", ["review_id"])
    op.create_index("ix_approvals_recommendation_id", "approvals", ["recommendation_id"])
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"])
    op.create_index("ix_approvals_session_id", "approvals", ["session_id"])

    op.create_table(
        "purchase_orders",
        sa.Column("purchase_order_id", sa.String(length=64), primary_key=True),
        sa.Column("approval_id", sa.String(length=64), nullable=False),
        sa.Column("store_id", sa.String(length=32), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("agent_recommended_quantity", sa.Integer(), nullable=False),
        sa.Column("human_proposed_quantity", sa.Integer(), nullable=False),
        sa.Column("approved_final_quantity", sa.Integer(), nullable=False),
        sa.Column("override_used", sa.Boolean(), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("approval_id", name="uq_po_approval_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_po_idempotency_key"),
    )
    op.create_index("ix_purchase_orders_approval_id", "purchase_orders", ["approval_id"])
    op.create_index("ix_purchase_orders_user_id", "purchase_orders", ["user_id"])
    op.create_index("ix_purchase_orders_session_id", "purchase_orders", ["session_id"])

    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("recommendation_id", sa.String(length=64), nullable=True),
        sa.Column("review_id", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("purchase_order_id", sa.String(length=64), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index("ix_audit_events_recommendation_id", "audit_events", ["recommendation_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_session_id", "audit_events", ["session_id"])

    op.create_table(
        "agent_run_states",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("recommendation_id", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("pending_tool_name", sa.String(length=128), nullable=True),
        sa.Column("pending_tool_args_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_run_idempotency_key"),
    )
    op.create_index("ix_agent_run_states_recommendation_id", "agent_run_states", ["recommendation_id"])
    op.create_index("ix_agent_run_states_user_id", "agent_run_states", ["user_id"])
    op.create_index("ix_agent_run_states_session_id", "agent_run_states", ["session_id"])


def downgrade() -> None:
    op.drop_table("agent_run_states")
    op.drop_table("audit_events")
    op.drop_table("purchase_orders")
    op.drop_table("approvals")
    op.drop_table("human_reviews")
    op.drop_table("recommendations")

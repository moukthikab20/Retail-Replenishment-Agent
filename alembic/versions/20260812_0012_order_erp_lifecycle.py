"""Order / ERP lifecycle hardening columns and status remap.

Revision ID: 20260812_0012
Revises: 20260812_0011
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0012"
down_revision: str | None = "20260812_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("order_intents") as batch_op:
        batch_op.add_column(
            sa.Column("transmission_idempotency_key", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(sa.Column("external_order_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("erp_provider", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_error_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("execution_id", sa.String(length=64), nullable=True))

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.add_column(sa.Column("external_order_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("erp_provider", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_error_code", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("transmission_idempotency_key", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(sa.Column("last_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(), nullable=True))

    # Remap legacy lifecycle statuses on both tables.
    for table, columns in (
        ("order_intents", ("status",)),
        ("purchase_orders", ("status", "order_status")),
    ):
        for column in columns:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'queued_for_erp' "
                    f"WHERE {column} = 'pending_erp'"
                )
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'transmission_failed' "
                    f"WHERE {column} = 'failed'"
                )
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'completed' "
                    f"WHERE {column} = 'transmitted'"
                )
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'erp_acknowledged' "
                    f"WHERE {column} = 'acknowledged'"
                )
            )

    op.execute(
        sa.text(
            "UPDATE order_intents "
            "SET transmission_idempotency_key = 'erp-order:' || order_intent_id "
            "WHERE transmission_idempotency_key IS NULL"
        )
    )

    with op.batch_alter_table("order_intents") as batch_op:
        batch_op.create_index(
            "uq_order_intent_transmission_idempotency_key",
            ["transmission_idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("order_intents") as batch_op:
        batch_op.drop_index("uq_order_intent_transmission_idempotency_key")

    for table, columns in (
        ("order_intents", ("status",)),
        ("purchase_orders", ("status", "order_status")),
    ):
        for column in columns:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'pending_erp' "
                    f"WHERE {column} = 'queued_for_erp'"
                )
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'failed' "
                    f"WHERE {column} = 'transmission_failed'"
                )
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'transmitted' "
                    f"WHERE {column} = 'completed'"
                )
            )
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = 'acknowledged' "
                    f"WHERE {column} = 'erp_acknowledged'"
                )
            )

    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("transmission_idempotency_key")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("last_error_code")
        batch_op.drop_column("erp_provider")
        batch_op.drop_column("acknowledged_at")
        batch_op.drop_column("external_order_id")

    with op.batch_alter_table("order_intents") as batch_op:
        batch_op.drop_column("execution_id")
        batch_op.drop_column("next_retry_at")
        batch_op.drop_column("last_attempt_at")
        batch_op.drop_column("last_error_message")
        batch_op.drop_column("last_error_code")
        batch_op.drop_column("acknowledged_at")
        batch_op.drop_column("erp_provider")
        batch_op.drop_column("external_order_id")
        batch_op.drop_column("transmission_idempotency_key")

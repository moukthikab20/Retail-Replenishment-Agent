"""Alembic migration: knowledge documents + chunks for semantic RAG.

Revision ID: 20260812_0013
Revises: 20260812_0012
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0013"
down_revision: str | None = "20260812_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("source_reference", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("access_scope", sa.String(length=64), nullable=False, server_default="public"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("store_id", sa.String(length=32), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("supplier_id", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("policy_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_documents_document_type", "knowledge_documents", ["document_type"])
    op.create_index("ix_knowledge_documents_access_scope", "knowledge_documents", ["access_scope"])
    op.create_index("ix_knowledge_documents_store_id", "knowledge_documents", ["store_id"])
    op.create_index("ix_knowledge_documents_sku", "knowledge_documents", ["sku"])
    op.create_index("ix_knowledge_documents_supplier_id", "knowledge_documents", ["supplier_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(length=80), primary_key=True),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_reference", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("embedding_ref", sa.String(length=128), nullable=True),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("access_scope", sa.String(length=64), nullable=False, server_default="public"),
        sa.Column("document_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("store_id", sa.String(length=32), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("supplier_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_doc_idx"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    op.create_index("ix_knowledge_chunks_access_scope", "knowledge_chunks", ["access_scope"])


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")

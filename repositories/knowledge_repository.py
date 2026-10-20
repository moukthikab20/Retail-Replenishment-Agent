"""Knowledge document / chunk persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database.models import KnowledgeChunkRow, KnowledgeDocumentRow
from memory.rag.contracts import KnowledgeChunk, KnowledgeDocument


def _parse_meta(raw: str | None) -> dict:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save_document(session: Session, document: KnowledgeDocument) -> KnowledgeDocument:
    now = datetime.now(timezone.utc)
    row = session.get(KnowledgeDocumentRow, document.document_id)
    values = dict(
        title=document.title,
        document_type=str(document.document_type),
        source=document.source,
        source_reference=document.source_reference,
        content=document.content,
        version=document.version,
        access_scope=str(document.access_scope),
        metadata_json=json.dumps(document.metadata or {}, default=str),
        store_id=document.store_id,
        sku=document.sku,
        supplier_id=document.supplier_id,
        category=document.category,
        policy_id=document.policy_id,
        updated_at=now,
    )
    if row is None:
        row = KnowledgeDocumentRow(
            document_id=document.document_id,
            created_at=document.created_at or now,
            **values,
        )
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    document.created_at = row.created_at
    document.updated_at = row.updated_at
    return document


def replace_chunks(session: Session, document_id: str, chunks: list[KnowledgeChunk]) -> None:
    session.execute(
        delete(KnowledgeChunkRow).where(KnowledgeChunkRow.document_id == document_id)
    )
    now = datetime.now(timezone.utc)
    for chunk in chunks:
        meta = dict(chunk.metadata or {})
        session.add(
            KnowledgeChunkRow(
                chunk_id=chunk.chunk_id,
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                metadata_json=json.dumps(meta, default=str),
                source_reference=chunk.source_reference,
                embedding_ref=chunk.embedding_ref,
                embedding_json=None,
                access_scope=str(meta.get("access_scope") or "public"),
                document_type=str(meta.get("document_type") or ""),
                title=str(meta.get("title") or ""),
                source=str(meta.get("source") or ""),
                store_id=meta.get("store_id"),
                sku=meta.get("sku"),
                supplier_id=meta.get("supplier_id"),
                created_at=now,
            )
        )
    session.flush()


def get_document(session: Session, document_id: str) -> KnowledgeDocument | None:
    row = session.get(KnowledgeDocumentRow, document_id)
    if row is None:
        return None
    return KnowledgeDocument(
        document_id=row.document_id,
        title=row.title,
        document_type=row.document_type,
        source=row.source,
        source_reference=row.source_reference,
        content=row.content,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=row.version,
        metadata=_parse_meta(row.metadata_json),
        access_scope=row.access_scope,
        store_id=row.store_id,
        sku=row.sku,
        supplier_id=row.supplier_id,
        category=row.category,
        policy_id=row.policy_id,
    )


def list_documents(session: Session, *, limit: int = 100) -> list[KnowledgeDocument]:
    stmt = (
        select(KnowledgeDocumentRow)
        .order_by(KnowledgeDocumentRow.updated_at.desc())
        .limit(max(1, min(int(limit or 100), 500)))
    )
    return [get_document(session, row.document_id) for row in session.scalars(stmt) if row]


def list_chunks_for_document(session: Session, document_id: str) -> list[KnowledgeChunk]:
    stmt = (
        select(KnowledgeChunkRow)
        .where(KnowledgeChunkRow.document_id == document_id)
        .order_by(KnowledgeChunkRow.chunk_index.asc())
    )
    out: list[KnowledgeChunk] = []
    for row in session.scalars(stmt):
        out.append(
            KnowledgeChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                text=row.text,
                metadata=_parse_meta(row.metadata_json),
                source_reference=row.source_reference,
                embedding_ref=row.embedding_ref,
            )
        )
    return out


def delete_document(session: Session, document_id: str) -> bool:
    session.execute(
        delete(KnowledgeChunkRow).where(KnowledgeChunkRow.document_id == document_id)
    )
    row = session.get(KnowledgeDocumentRow, document_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True

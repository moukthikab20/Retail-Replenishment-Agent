"""Knowledge ingestion — document → chunks → embed → upsert."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from database.connection import get_session, init_db
from memory.rag.chunking import chunk_document
from memory.rag.contracts import AccessScope, DocumentType, KnowledgeDocument, new_document_id
from memory.rag.embeddings import get_embedding_provider
from memory.rag.vector_store import get_vector_store
from repositories import knowledge_repository

logger = logging.getLogger(__name__)


def ingest_knowledge(
    *,
    title: str,
    document_type: str | DocumentType,
    source: str,
    source_reference: str,
    content: str,
    access_scope: str | AccessScope = AccessScope.PUBLIC,
    metadata: dict[str, Any] | None = None,
    document_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    category: str | None = None,
    policy_id: str | None = None,
    version: str = "v1",
) -> dict[str, Any]:
    """Persist a knowledge document, chunk it, embed, and upsert vectors."""
    init_db()
    now = datetime.now(timezone.utc)
    doc = KnowledgeDocument(
        document_id=document_id or new_document_id(
            str(document_type).upper()[:3] if document_type else "DOC"
        ),
        title=title,
        document_type=document_type,
        source=source,
        source_reference=source_reference,
        content=content,
        created_at=now,
        updated_at=now,
        version=version,
        metadata=dict(metadata or {}),
        access_scope=access_scope,
        store_id=store_id,
        sku=sku,
        supplier_id=supplier_id,
        category=category,
        policy_id=policy_id,
    )
    chunks = chunk_document(doc)
    embedder = get_embedding_provider()
    vectors = embedder.embed([c.text for c in chunks]) if chunks else []
    for chunk, _vec in zip(chunks, vectors):
        chunk.embedding_ref = f"{embedder.provider_name}:{chunk.chunk_id}"

    with get_session() as session:
        knowledge_repository.save_document(session, doc)
        knowledge_repository.replace_chunks(session, doc.document_id, chunks)

    if chunks:
        store = get_vector_store()
        payloads = []
        for chunk in chunks:
            payloads.append(
                {
                    "document_id": doc.document_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "source_reference": chunk.source_reference,
                    "access_scope": str(doc.access_scope),
                    "document_type": str(doc.document_type),
                    "title": doc.title,
                    "source": doc.source,
                    "store_id": doc.store_id,
                    "sku": doc.sku,
                    "supplier_id": doc.supplier_id,
                    "citation": doc.citation(),
                }
            )
        store.upsert(
            chunk_ids=[c.chunk_id for c in chunks],
            vectors=vectors,
            payloads=payloads,
        )

    return {
        "document_id": doc.document_id,
        "chunk_count": len(chunks),
        "citation": doc.citation(),
        "access_scope": str(doc.access_scope),
        "document_type": str(doc.document_type),
    }


def delete_knowledge(document_id: str) -> bool:
    init_db()
    get_vector_store().delete_document(document_id)
    with get_session() as session:
        return knowledge_repository.delete_document(session, document_id)


def seed_demo_knowledge() -> list[dict[str, Any]]:
    """Non-authoritative demo/test corpus."""
    samples = [
        {
            "document_id": "POL-004",
            "title": "High-value order approval",
            "document_type": DocumentType.POLICY,
            "source": "demo_policy_pack",
            "source_reference": "POL-004",
            "content": "Orders over $5,000 require Category Manager approval.",
            "access_scope": AccessScope.PUBLIC,
            "policy_id": "POL-004",
        },
        {
            "document_id": "SUP-12",
            "title": "Supplier ABC lead time",
            "document_type": DocumentType.SUPPLIER,
            "source": "demo_supplier_sop",
            "source_reference": "SUP-12",
            "content": "Supplier ABC normally requires 5 business days lead time.",
            "access_scope": AccessScope.OPERATIONS,
            "supplier_id": "ABC",
        },
        {
            "document_id": "OPS-3",
            "title": "ERP invalid supplier code",
            "document_type": DocumentType.OPERATIONS,
            "source": "demo_operations_sop",
            "source_reference": "OPS-3",
            "content": (
                "ERP rejection caused by invalid supplier code requires master-data review."
            ),
            "access_scope": AccessScope.OPERATIONS,
        },
    ]
    results = []
    for sample in samples:
        results.append(ingest_knowledge(**sample))
    return results

"""Semantic RAG package — extends Memory & Knowledge Engine."""

from __future__ import annotations

from memory.rag.contracts import (
    AccessScope,
    DocumentType,
    KnowledgeChunk,
    KnowledgeDocument,
    SemanticHit,
    SemanticSearchResult,
)
from memory.rag.embeddings import (
    get_embedding_provider,
    reset_embedding_provider,
    validate_embedding_provider_configuration,
)
from memory.rag.ingestion import delete_knowledge, ingest_knowledge, seed_demo_knowledge
from memory.rag.search import semantic_search
from memory.rag.vector_store import get_vector_store, reset_vector_store

__all__ = [
    "AccessScope",
    "DocumentType",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "SemanticHit",
    "SemanticSearchResult",
    "delete_knowledge",
    "get_embedding_provider",
    "get_vector_store",
    "ingest_knowledge",
    "reset_embedding_provider",
    "reset_vector_store",
    "seed_demo_knowledge",
    "semantic_search",
    "validate_embedding_provider_configuration",
]

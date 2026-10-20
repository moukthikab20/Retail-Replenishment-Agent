"""RAG / semantic knowledge contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field


class DocumentType(StrEnum):
    POLICY = "policy"
    SOP = "sop"
    SUPPLIER = "supplier"
    OPERATIONS = "operations"
    CATEGORY = "category"
    TRAINING = "training"
    TECHNICAL = "technical"


class AccessScope(StrEnum):
    PUBLIC = "public"
    OPERATIONS = "operations"
    PLANNER = "planner"
    ADMINISTRATOR = "administrator"


class KnowledgeDocument(BaseModel):
    document_id: str
    title: str
    document_type: DocumentType | str
    source: str
    source_reference: str
    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: str = "v1"
    metadata: dict[str, Any] = Field(default_factory=dict)
    access_scope: AccessScope | str = AccessScope.PUBLIC
    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    category: str | None = None
    policy_id: str | None = None

    def citation(self) -> str:
        """Human-readable citation label — never fabricated beyond stored fields."""
        ref = (self.source_reference or self.document_id or "").strip()
        dtype = str(self.document_type or "knowledge").replace("_", " ").title()
        if ref:
            return f"[{dtype} {ref}]"
        return f"[{dtype} {self.document_id}]"


class KnowledgeChunk(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_reference: str = ""
    embedding_ref: str | None = None


class SemanticHit(BaseModel):
    chunk_id: str
    document_id: str
    text: str
    score: float
    source: str
    source_reference: str
    citation: str
    retrieval_method: str = "semantic"
    document_type: str | None = None
    access_scope: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticSearchResult(BaseModel):
    hits: list[SemanticHit] = Field(default_factory=list)
    query: str = ""
    query_hash: str = ""
    method: str = "semantic"
    duration_ms: float = 0.0
    provider: str = "mock"
    degraded: bool = False
    degradation_reason: str | None = None
    score_min: float | None = None
    score_max: float | None = None
    context_size_chars: int = 0
    source_ids: list[str] = Field(default_factory=list)

    def to_ops_summary(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "result_count": len(self.hits),
            "source_ids": list(self.source_ids),
            "retrieval_latency_ms": round(self.duration_ms, 2),
            "context_size_chars": self.context_size_chars,
            "score_range": {
                "min": self.score_min,
                "max": self.score_max,
            },
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
            "provider": self.provider,
            "citations": [h.citation for h in self.hits],
        }


def new_document_id(prefix: str = "DOC") -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


def new_chunk_id(document_id: str, index: int) -> str:
    return f"{document_id}-C{index:04d}"


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def health_check(self) -> dict[str, Any]:
        ...


@runtime_checkable
class VectorStore(Protocol):
    store_name: str

    def upsert(
        self,
        *,
        chunk_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        ...

    def delete_document(self, document_id: str) -> int:
        ...

    def search(
        self,
        vector: list[float],
        *,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        ...

    def health_check(self) -> dict[str, Any]:
        ...

"""Memory / knowledge contracts — vector-store ready."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from memory.types import MemoryType


class MemoryRecord(BaseModel):
    """One retrieved memory item. Embedding fields reserved for future vector backends."""

    record_id: str
    memory_type: MemoryType
    title: str
    summary: str = ""
    occurred_at: datetime | None = None
    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    purchase_order_id: str | None = None
    execution_id: str | None = None
    source: str = "database"
    score: float | None = None  # semantic ranking when present
    embedding_ref: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    source_reference: str | None = None
    retrieval_method: str | None = None  # structured | semantic | hybrid
    citation: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryQuery(BaseModel):
    memory_types: list[MemoryType] = Field(default_factory=list)
    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    purchase_order_id: str | None = None
    execution_id: str | None = None
    limit: int = 10
    include_failures: bool = False
    related_only: bool = True


class RetrievalResult(BaseModel):
    records: list[MemoryRecord] = Field(default_factory=list)
    source: str
    memory_type: MemoryType | None = None
    query: MemoryQuery | None = None
    duration_ms: float = 0.0
    truncated: bool = False
    ops: dict[str, Any] = Field(default_factory=dict)


class AssembledContext(BaseModel):
    """Unified execution context — the only historical object for LLM workflows."""

    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    purchase_order_id: str | None = None
    execution_id: str | None = None
    records_by_type: dict[str, list[MemoryRecord]] = Field(default_factory=dict)
    llm_context: dict[str, Any] = Field(default_factory=dict)
    knowledge_sources: list[str] = Field(default_factory=list)
    record_count: int = 0
    context_size_chars: int = 0
    retrieval_latency_ms: float = 0.0
    provider_name: str = "database"
    assembled_at: datetime | None = None

    def to_ops_summary(self) -> dict[str, Any]:
        rag = (self.llm_context or {}).get("rag_ops") or {}
        return {
            "memory_retrieved": self.record_count > 0,
            "knowledge_sources": list(self.knowledge_sources),
            "retrieved_records": self.record_count,
            "records_by_type": {
                key: len(vals) for key, vals in self.records_by_type.items()
            },
            "context_size_chars": self.context_size_chars,
            "retrieval_latency_ms": round(self.retrieval_latency_ms, 2),
            "provider_name": self.provider_name,
            "citations": list((self.llm_context or {}).get("citations") or []),
            "knowledge_retrieval": {
                "method": rag.get("method"),
                "result_count": rag.get("result_count"),
                "source_ids": rag.get("source_ids") or [],
                "retrieval_latency_ms": rag.get("retrieval_latency_ms"),
                "context_size_chars": rag.get("context_size_chars"),
                "score_range": rag.get("score_range") or {},
                "degraded": bool(rag.get("degraded")),
                "degradation_reason": rag.get("degradation_reason"),
                "citations": rag.get("citations") or [],
            },
        }


@runtime_checkable
class MemoryProvider(Protocol):
    """Historical memory source. Implementations may be SQL or vector-backed."""

    provider_name: str

    def retrieve(self, query: MemoryQuery) -> RetrievalResult:
        ...

    def health_check(self) -> dict[str, Any]:
        ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    """Cross-cutting knowledge façade (may wrap one or more MemoryProviders)."""

    provider_name: str

    def retrieve(self, query: MemoryQuery) -> RetrievalResult:
        ...

    def health_check(self) -> dict[str, Any]:
        ...


@runtime_checkable
class MemoryStoreBackend(Protocol):
    """Low-level store — SQL today; vector indexes later without API changes."""

    backend_name: str

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        ...

    def health_check(self) -> dict[str, Any]:
        ...

"""Semantic / hybrid knowledge search with policy limits and access control."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from config import (
    RAG_ENABLED,
    RAG_MAX_CONTEXT_CHARS,
    RAG_MAX_RESULTS,
    RAG_MIN_SCORE,
)
from memory.rag.access import allowed_scopes_for_role
from memory.rag.contracts import SemanticHit, SemanticSearchResult
from memory.rag.embeddings import get_embedding_provider
from memory.rag.sanitize import format_retrieved_knowledge_block
from memory.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)

AUDIT_KNOWLEDGE_SEARCH_STARTED = "knowledge_search_started"
AUDIT_KNOWLEDGE_SEARCH_COMPLETED = "knowledge_search_completed"
AUDIT_KNOWLEDGE_SEARCH_FAILED = "knowledge_search_failed"


def _query_hash(query: str) -> str:
    return hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:16]


def _record_audit(event_type: str, *, execution_id: str | None, details: dict[str, Any]) -> None:
    try:
        from config import MEMORY_AUDIT_PERSIST
        from database.connection import get_session, init_db
        from memory.audit import record_retrieval_audit
        from repositories import audit_repository

        # Always keep in-process retrieval audit style trail via memory audit helper when useful.
        if event_type == AUDIT_KNOWLEDGE_SEARCH_COMPLETED:
            record_retrieval_audit(
                execution_id=execution_id,
                retrieval_source=f"rag:{details.get('method')}",
                record_count=int(details.get("result_count") or 0),
                duration_ms=float(details.get("latency_ms") or 0),
                memory_types=["semantic_knowledge"],
                details={
                    "query_hash": details.get("query_hash"),
                    "provider": details.get("provider"),
                    "source_ids": details.get("source_ids"),
                    "retrieval_method": details.get("method"),
                },
                persist=False,
            )
        if MEMORY_AUDIT_PERSIST:
            init_db()
            with get_session() as session:
                audit_repository.write_audit_event(
                    session,
                    event_type,
                    actor="knowledge_retrieval",
                    actor_type="system",
                    run_id=execution_id,
                    details=details,
                )
    except Exception:  # noqa: BLE001
        pass


def apply_retrieval_policy(
    hits: list[SemanticHit],
    *,
    max_results: int | None = None,
    max_context_chars: int | None = None,
    min_score: float | None = None,
) -> list[SemanticHit]:
    limit = max(1, int(max_results if max_results is not None else RAG_MAX_RESULTS))
    char_cap = max(200, int(max_context_chars if max_context_chars is not None else RAG_MAX_CONTEXT_CHARS))
    threshold = float(min_score if min_score is not None else RAG_MIN_SCORE)

    filtered = [h for h in hits if h.score >= threshold]
    # Deduplicate by document_id (prefer highest score), then diversify.
    by_doc: dict[str, SemanticHit] = {}
    for hit in sorted(filtered, key=lambda h: h.score, reverse=True):
        if hit.document_id not in by_doc:
            by_doc[hit.document_id] = hit
    diversified = list(by_doc.values())
    diversified.sort(key=lambda h: h.score, reverse=True)

    selected: list[SemanticHit] = []
    used = 0
    for hit in diversified:
        if len(selected) >= limit:
            break
        size = len(hit.text) + len(hit.citation)
        if selected and used + size > char_cap:
            continue
        selected.append(hit)
        used += size
    return selected


def semantic_search(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
    actor_role: str | None = None,
    execution_id: str | None = None,
    min_score: float | None = None,
) -> SemanticSearchResult:
    started = time.perf_counter()
    qhash = _query_hash(query)
    method = "semantic"
    if not RAG_ENABLED:
        return SemanticSearchResult(
            hits=[],
            query=query,
            query_hash=qhash,
            method=method,
            duration_ms=0.0,
            degraded=True,
            degradation_reason="rag_disabled",
        )

    _record_audit(
        AUDIT_KNOWLEDGE_SEARCH_STARTED,
        execution_id=execution_id,
        details={"query_hash": qhash, "method": method},
    )
    try:
        embedder = get_embedding_provider()
        store = get_vector_store()
        vector = embedder.embed([query or ""])[0]
        allowed = allowed_scopes_for_role(actor_role)
        search_filters = dict(filters or {})
        search_filters["allowed_scopes"] = allowed
        raw = store.search(
            vector,
            limit=max(limit or RAG_MAX_RESULTS, RAG_MAX_RESULTS) * 3,
            filters=search_filters,
            min_score=float(min_score if min_score is not None else RAG_MIN_SCORE),
        )
        hits: list[SemanticHit] = []
        for item in raw:
            payload = item.get("payload") or {}
            scope = payload.get("access_scope") or "public"
            if scope not in allowed:
                continue
            citation = payload.get("citation") or (
                f"[{str(payload.get('document_type') or 'Knowledge').title()} "
                f"{payload.get('source_reference') or payload.get('document_id')}]"
            )
            hits.append(
                SemanticHit(
                    chunk_id=str(item.get("chunk_id")),
                    document_id=str(payload.get("document_id") or ""),
                    text=str(payload.get("text") or ""),
                    score=float(item.get("score") or 0.0),
                    source=str(payload.get("source") or "knowledge"),
                    source_reference=str(payload.get("source_reference") or ""),
                    citation=citation,
                    retrieval_method=method,
                    document_type=payload.get("document_type"),
                    access_scope=scope,
                    title=payload.get("title"),
                    metadata={
                        k: v
                        for k, v in payload.items()
                        if k not in {"text", "embedding", "vector"}
                    },
                )
            )
        hits = apply_retrieval_policy(hits, max_results=limit, min_score=min_score)
        duration = (time.perf_counter() - started) * 1000.0
        block = format_retrieved_knowledge_block(
            [{"citation": h.citation, "text": h.text} for h in hits]
        )
        result = SemanticSearchResult(
            hits=hits,
            query=query,
            query_hash=qhash,
            method=method,
            duration_ms=duration,
            provider=embedder.provider_name,
            score_min=min((h.score for h in hits), default=None),
            score_max=max((h.score for h in hits), default=None),
            context_size_chars=len(block),
            source_ids=[h.document_id for h in hits],
        )
        _record_audit(
            AUDIT_KNOWLEDGE_SEARCH_COMPLETED,
            execution_id=execution_id,
            details={
                "query_hash": qhash,
                "method": method,
                "provider": embedder.provider_name,
                "result_count": len(hits),
                "source_ids": result.source_ids,
                "latency_ms": duration,
            },
        )
        return result
    except Exception as exc:  # noqa: BLE001
        duration = (time.perf_counter() - started) * 1000.0
        logger.warning("semantic_search_failed err=%s", exc)
        _record_audit(
            AUDIT_KNOWLEDGE_SEARCH_FAILED,
            execution_id=execution_id,
            details={
                "query_hash": qhash,
                "method": method,
                "error": type(exc).__name__,
                "latency_ms": duration,
            },
        )
        return SemanticSearchResult(
            hits=[],
            query=query,
            query_hash=qhash,
            method=method,
            duration_ms=duration,
            degraded=True,
            degradation_reason=type(exc).__name__,
        )

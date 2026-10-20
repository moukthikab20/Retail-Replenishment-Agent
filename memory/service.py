"""Memory service façade — business code uses this, never queries history DBs directly."""

from __future__ import annotations

import logging
from typing import Any

from memory.contracts import AssembledContext, RetrievalResult
from memory.factory import (
    get_context_assembler,
    get_memory_provider,
    get_retrieval_engine,
    memory_provider_health,
    reset_memory_providers,
)

logger = logging.getLogger(__name__)


def assemble_execution_context(
    *,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    purchase_order_id: str | None = None,
    supplier_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    execution_id: str | None = None,
    limit: int | None = None,
    semantic_query: str | None = None,
    actor_role: str | None = None,
    conversation_context: str | None = None,
) -> AssembledContext:
    assembler = get_context_assembler()
    return assembler.assemble(
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        purchase_order_id=purchase_order_id,
        supplier_id=supplier_id,
        store_id=store_id,
        sku=sku,
        execution_id=execution_id,
        limit=limit,
        semantic_query=semantic_query,
        actor_role=actor_role,
        conversation_context=conversation_context,
    )


def retrieve_related_memory(
    *,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    purchase_order_id: str | None = None,
    execution_id: str | None = None,
    limit: int | None = None,
) -> RetrievalResult:
    engine = get_retrieval_engine()
    return engine.retrieve_related(
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        store_id=store_id,
        sku=sku,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        execution_id=execution_id,
        limit=limit,
    )


def attach_memory_to_execution_context(
    context: dict[str, Any] | None,
    *,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    purchase_order_id: str | None = None,
    supplier_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    semantic_query: str | None = None,
    actor_role: str | None = None,
) -> dict[str, Any]:
    """
    Enrich an execution context with assembled memory (fail-soft).

    Never raises — agent execution continues if memory is unavailable.
    """
    base = dict(context or {})
    try:
        assembled = assemble_execution_context(
            recommendation_id=recommendation_id or base.get("recommendation_id"),
            approval_id=approval_id or base.get("approval_id"),
            purchase_order_id=purchase_order_id or base.get("purchase_order_id"),
            supplier_id=supplier_id or base.get("supplier_id"),
            store_id=store_id or base.get("store_id"),
            sku=sku or base.get("sku"),
            execution_id=execution_id,
            semantic_query=semantic_query
            or base.get("semantic_query")
            or base.get("goal")
            or base.get("user_input"),
            actor_role=actor_role or base.get("actor_role"),
            conversation_context=base.get("conversation_context"),
        )
        base["memory"] = assembled.llm_context
        base["memory_ops"] = assembled.to_ops_summary()
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_attach_failed execution_id=%s err=%s", execution_id, exc)
        base.setdefault(
            "memory_ops",
            {
                "memory_retrieved": False,
                "knowledge_sources": [],
                "retrieved_records": 0,
                "records_by_type": {},
                "context_size_chars": 0,
                "retrieval_latency_ms": 0.0,
                "provider_name": "unavailable",
                "knowledge_retrieval": {"degraded": True, "degradation_reason": "memory_unavailable"},
                "error": "memory_unavailable",
            },
        )
    return base


def memory_health() -> dict[str, Any]:
    return memory_provider_health()


__all__ = [
    "assemble_execution_context",
    "attach_memory_to_execution_context",
    "get_memory_provider",
    "memory_health",
    "reset_memory_providers",
    "retrieve_related_memory",
]

"""ContextAssembler — builds one unified execution context for LLM workflows."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from memory.audit import record_retrieval_audit
from memory.contracts import AssembledContext, MemoryRecord
from memory.retrieval import RetrievalEngine
from memory.types import MemoryType


class ContextAssembler:
    """Assembles historical memory + optional semantic knowledge into AssembledContext."""

    def __init__(self, engine: RetrievalEngine) -> None:
        self._engine = engine

    def assemble(
        self,
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
        started = time.perf_counter()
        related = self._engine.retrieve_related(
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=store_id,
            sku=sku,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            limit=limit,
            execution_id=execution_id,
            persist_audit=False,
        )
        records = list(related.records)
        for record in records:
            record.retrieval_method = record.retrieval_method or "structured"

        knowledge_records: list[MemoryRecord] = []
        rag_ops: dict[str, Any] = {
            "method": None,
            "result_count": 0,
            "source_ids": [],
            "retrieval_latency_ms": 0.0,
            "context_size_chars": 0,
            "score_range": {"min": None, "max": None},
            "degraded": False,
            "degradation_reason": None,
            "citations": [],
        }
        query = (semantic_query or "").strip()
        if not query:
            # Default narrative query from anchors — enables hybrid without caller text.
            bits = [x for x in (store_id, sku, supplier_id) if x]
            query = (
                " ".join(bits) + " policy approval escalation operations guidance"
            ).strip()

        try:
            from config import RAG_ENABLED

            if RAG_ENABLED and query:
                semantic = self._engine.semantic_search(
                    query,
                    filters={
                        "store_id": store_id,
                        "sku": sku,
                        "supplier_id": supplier_id,
                    },
                    limit=limit,
                    actor_role=actor_role,
                    execution_id=execution_id,
                )
                knowledge_records = list(semantic.records)
                if semantic.ops:
                    rag_ops.update(dict(semantic.ops))
                elif knowledge_records and knowledge_records[0].payload.get("rag_ops"):
                    rag_ops.update(
                        dict(knowledge_records[0].payload.get("rag_ops") or {})
                    )
                else:
                    rag_ops.update(
                        {
                            "method": "semantic",
                            "result_count": len(knowledge_records),
                            "source_ids": [
                                r.document_id for r in knowledge_records if r.document_id
                            ],
                            "retrieval_latency_ms": semantic.duration_ms,
                            "citations": [
                                r.citation for r in knowledge_records if r.citation
                            ],
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            rag_ops["degraded"] = True
            rag_ops["degradation_reason"] = type(exc).__name__

        by_type: dict[str, list[MemoryRecord]] = {}
        for record in records:
            by_type.setdefault(str(record.memory_type), []).append(record)

        knowledge_section = [
            {
                "citation": r.citation,
                "document_id": r.document_id,
                "chunk_id": r.chunk_id,
                "source_reference": r.source_reference,
                "score": r.score,
                "text": (r.payload or {}).get("text") or r.summary,
                "retrieval_method": r.retrieval_method or "semantic",
            }
            for r in knowledge_records
        ]

        llm_context = {
            "anchors": {
                "recommendation_id": recommendation_id,
                "approval_id": approval_id,
                "purchase_order_id": purchase_order_id,
                "supplier_id": supplier_id,
                "store_id": store_id,
                "sku": sku,
                "execution_id": execution_id,
            },
            "memory": {
                key: [
                    {
                        "record_id": r.record_id,
                        "title": r.title,
                        "summary": r.summary,
                        "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                        "payload": r.payload,
                        "retrieval_method": r.retrieval_method or "structured",
                    }
                    for r in vals
                ]
                for key, vals in by_type.items()
            },
            "retrieved_knowledge": knowledge_section,
            "conversation_context": conversation_context or "",
            "prior_failures": [
                {
                    "record_id": r.record_id,
                    "memory_type": str(r.memory_type),
                    "summary": r.summary,
                }
                for r in records
                if r.payload.get("is_failure")
            ],
            "prior_approvals": [
                {
                    "record_id": r.record_id,
                    "summary": r.summary,
                }
                for r in by_type.get(MemoryType.APPROVAL.value, [])
            ],
            "prior_orders": [
                {
                    "record_id": r.record_id,
                    "summary": r.summary,
                }
                for r in by_type.get(MemoryType.ERP.value, [])
            ],
            "knowledge_sources": sorted(
                {r.source for r in records}
                | {r.source for r in knowledge_records}
                | {self._engine.provider_name}
            ),
            "citations": [item["citation"] for item in knowledge_section if item.get("citation")],
            "rag_ops": rag_ops,
        }
        encoded = json.dumps(llm_context, default=str, sort_keys=True)
        latency = (time.perf_counter() - started) * 1000.0
        record_retrieval_audit(
            execution_id=execution_id,
            retrieval_source=f"{self._engine.provider_name}:assemble",
            record_count=len(records) + len(knowledge_records),
            duration_ms=latency,
            memory_types=sorted(set(list(by_type.keys()) + (["knowledge"] if knowledge_records else []))),
            details={
                "store_id": store_id,
                "sku": sku,
                "supplier_id": supplier_id,
                "recommendation_id": recommendation_id,
                "approval_id": approval_id,
                "purchase_order_id": purchase_order_id,
                "context_size_chars": len(encoded),
                "semantic_count": len(knowledge_records),
                "rag_degraded": rag_ops.get("degraded"),
            },
            persist=True,
        )
        return AssembledContext(
            store_id=store_id,
            sku=sku,
            supplier_id=supplier_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            purchase_order_id=purchase_order_id,
            execution_id=execution_id,
            records_by_type={
                **by_type,
                **(
                    {"knowledge": knowledge_records}
                    if knowledge_records
                    else {}
                ),
            },
            llm_context=llm_context,
            knowledge_sources=list(llm_context["knowledge_sources"]),
            record_count=len(records) + len(knowledge_records),
            context_size_chars=len(encoded),
            retrieval_latency_ms=latency,
            provider_name=self._engine.provider_name,
            assembled_at=datetime.now(timezone.utc),
        )

    def assemble_for_llm(self, **kwargs: Any) -> dict[str, Any]:
        """Return only the unified LLM context payload."""
        return self.assemble(**kwargs).llm_context

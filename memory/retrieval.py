"""RetrievalEngine — typed retrieval helpers with configurable limits."""

from __future__ import annotations

from typing import Any

from memory.audit import record_retrieval_audit
from memory.contracts import MemoryProvider, MemoryQuery, MemoryRecord, RetrievalResult
from memory.types import MemoryType


class RetrievalEngine:
    """High-level retrieval API used by ContextAssembler and the memory service."""

    def __init__(
        self,
        provider: MemoryProvider,
        *,
        default_limit: int = 10,
        max_limit: int = 50,
    ) -> None:
        self._provider = provider
        self.default_limit = max(1, int(default_limit))
        self.max_limit = max(self.default_limit, int(max_limit))

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "provider_name", "unknown")

    def _clamp_limit(self, limit: int | None) -> int:
        value = self.default_limit if limit is None else int(limit)
        return max(1, min(value, self.max_limit))

    def _run(
        self,
        query: MemoryQuery,
        *,
        execution_id: str | None = None,
        audit_source: str | None = None,
        persist_audit: bool = True,
    ) -> RetrievalResult:
        query.limit = self._clamp_limit(query.limit)
        result = self._provider.retrieve(query)
        record_retrieval_audit(
            execution_id=execution_id or query.execution_id,
            retrieval_source=audit_source or result.source or self.provider_name,
            record_count=len(result.records),
            duration_ms=result.duration_ms,
            memory_types=[str(t) for t in query.memory_types],
            details={
                "store_id": query.store_id,
                "sku": query.sku,
                "supplier_id": query.supplier_id,
                "recommendation_id": query.recommendation_id,
                "approval_id": query.approval_id,
                "include_failures": query.include_failures,
            },
            persist=persist_audit,
        )
        return result

    def retrieve(
        self,
        query: MemoryQuery,
        *,
        execution_id: str | None = None,
        persist_audit: bool = True,
    ) -> RetrievalResult:
        return self._run(query, execution_id=execution_id, persist_audit=persist_audit)

    def retrieve_recent(
        self,
        *,
        memory_types: list[MemoryType] | None = None,
        limit: int | None = None,
        execution_id: str | None = None,
        persist_audit: bool = True,
        **filters: Any,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=list(memory_types or []),
            limit=self._clamp_limit(limit),
            related_only=False,
            store_id=filters.get("store_id"),
            sku=filters.get("sku"),
            supplier_id=filters.get("supplier_id"),
            recommendation_id=filters.get("recommendation_id"),
            approval_id=filters.get("approval_id"),
            purchase_order_id=filters.get("purchase_order_id"),
            execution_id=execution_id or filters.get("execution_id"),
        )
        return self._run(
            query,
            execution_id=execution_id,
            audit_source=f"{self.provider_name}:recent",
            persist_audit=persist_audit,
        )

    def retrieve_related(
        self,
        *,
        recommendation_id: str | None = None,
        approval_id: str | None = None,
        store_id: str | None = None,
        sku: str | None = None,
        supplier_id: str | None = None,
        purchase_order_id: str | None = None,
        limit: int | None = None,
        execution_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
        persist_audit: bool = True,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=list(memory_types or list(MemoryType)),
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=store_id,
            sku=sku,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            limit=self._clamp_limit(limit),
            related_only=True,
            execution_id=execution_id,
        )
        return self._run(
            query,
            execution_id=execution_id,
            audit_source=f"{self.provider_name}:related",
            persist_audit=persist_audit,
        )

    def retrieve_by_supplier(
        self,
        supplier_id: str,
        *,
        limit: int | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=[MemoryType.SUPPLIER, MemoryType.ERP, MemoryType.RECOMMENDATION],
            supplier_id=supplier_id,
            limit=self._clamp_limit(limit),
            related_only=True,
            execution_id=execution_id,
        )
        return self._run(
            query, execution_id=execution_id, audit_source=f"{self.provider_name}:by_supplier"
        )

    def retrieve_by_store(
        self,
        store_id: str,
        *,
        limit: int | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=[
                MemoryType.RECOMMENDATION,
                MemoryType.INVENTORY,
                MemoryType.DECISION,
                MemoryType.ERP,
            ],
            store_id=store_id,
            limit=self._clamp_limit(limit),
            related_only=True,
            execution_id=execution_id,
        )
        return self._run(
            query, execution_id=execution_id, audit_source=f"{self.provider_name}:by_store"
        )

    def retrieve_by_sku(
        self,
        sku: str,
        *,
        store_id: str | None = None,
        limit: int | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=[
                MemoryType.RECOMMENDATION,
                MemoryType.INVENTORY,
                MemoryType.SUPPLIER,
                MemoryType.ERP,
            ],
            sku=sku,
            store_id=store_id,
            limit=self._clamp_limit(limit),
            related_only=True,
            execution_id=execution_id,
        )
        return self._run(
            query, execution_id=execution_id, audit_source=f"{self.provider_name}:by_sku"
        )

    def retrieve_previous_failures(
        self,
        *,
        store_id: str | None = None,
        sku: str | None = None,
        recommendation_id: str | None = None,
        limit: int | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=[MemoryType.EXECUTION, MemoryType.ERP],
            store_id=store_id,
            sku=sku,
            recommendation_id=recommendation_id,
            limit=self._clamp_limit(limit),
            include_failures=True,
            related_only=True,
            execution_id=execution_id,
        )
        result = self._run(
            query, execution_id=execution_id, audit_source=f"{self.provider_name}:failures"
        )
        failures = [
            r
            for r in result.records
            if r.payload.get("is_failure")
            or (r.memory_type == MemoryType.EXECUTION and "failed" in (r.summary or ""))
        ]
        result.records = failures
        return result

    def retrieve_previous_approvals(
        self,
        *,
        recommendation_id: str | None = None,
        store_id: str | None = None,
        sku: str | None = None,
        limit: int | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=[MemoryType.APPROVAL, MemoryType.DECISION],
            recommendation_id=recommendation_id,
            store_id=store_id,
            sku=sku,
            limit=self._clamp_limit(limit),
            related_only=True,
            execution_id=execution_id,
        )
        return self._run(
            query, execution_id=execution_id, audit_source=f"{self.provider_name}:approvals"
        )

    def retrieve_previous_orders(
        self,
        *,
        store_id: str | None = None,
        sku: str | None = None,
        supplier_id: str | None = None,
        purchase_order_id: str | None = None,
        limit: int | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        query = MemoryQuery(
            memory_types=[MemoryType.ERP, MemoryType.SUPPLIER],
            store_id=store_id,
            sku=sku,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            limit=self._clamp_limit(limit),
            related_only=True,
            execution_id=execution_id,
        )
        return self._run(
            query, execution_id=execution_id, audit_source=f"{self.provider_name}:orders"
        )

    def merge_records(self, *results: RetrievalResult) -> list[MemoryRecord]:
        seen: set[str] = set()
        merged: list[MemoryRecord] = []
        for result in results:
            for record in result.records:
                key = f"{record.memory_type}:{record.record_id}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(record)
        return merged

    def _hit_to_record(self, hit) -> MemoryRecord:
        from memory.rag.contracts import SemanticHit

        assert isinstance(hit, SemanticHit)
        dtype = (hit.document_type or "").lower()
        mem_type = MemoryType.KNOWLEDGE
        if dtype == "policy":
            mem_type = MemoryType.POLICY
        elif dtype == "supplier":
            mem_type = MemoryType.SUPPLIER
        return MemoryRecord(
            record_id=hit.chunk_id,
            memory_type=mem_type,
            title=hit.title or hit.citation,
            summary=hit.text[:300],
            store_id=(hit.metadata or {}).get("store_id"),
            sku=(hit.metadata or {}).get("sku"),
            supplier_id=(hit.metadata or {}).get("supplier_id"),
            source=hit.source,
            score=hit.score,
            document_id=hit.document_id,
            chunk_id=hit.chunk_id,
            source_reference=hit.source_reference,
            retrieval_method=hit.retrieval_method,
            citation=hit.citation,
            payload={
                "text": hit.text,
                "access_scope": hit.access_scope,
                "document_type": hit.document_type,
                "citation": hit.citation,
            },
        )

    def semantic_search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        actor_role: str | None = None,
        execution_id: str | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        from memory.rag.search import semantic_search as _semantic

        started = __import__("time").perf_counter()
        result = _semantic(
            query,
            filters=filters,
            limit=self._clamp_limit(limit),
            actor_role=actor_role,
            execution_id=execution_id,
            min_score=min_score,
        )
        records = [self._hit_to_record(h) for h in result.hits]
        duration = ( __import__("time").perf_counter() - started) * 1000.0
        ops = result.to_ops_summary()
        out = RetrievalResult(
            records=records,
            source=f"semantic:{result.provider}",
            query=None,
            duration_ms=result.duration_ms or duration,
            truncated=False,
            ops=ops,
        )
        for record in out.records:
            record.payload["rag_ops"] = ops
        return out

    def hybrid_search(
        self,
        query: str,
        *,
        structured_filters: dict[str, Any] | None = None,
        limit: int | None = None,
        actor_role: str | None = None,
        execution_id: str | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        filters = dict(structured_filters or {})
        structured = self.retrieve_related(
            recommendation_id=filters.get("recommendation_id"),
            approval_id=filters.get("approval_id"),
            store_id=filters.get("store_id"),
            sku=filters.get("sku"),
            supplier_id=filters.get("supplier_id"),
            purchase_order_id=filters.get("purchase_order_id"),
            limit=limit,
            execution_id=execution_id,
            persist_audit=False,
        )
        for record in structured.records:
            record.retrieval_method = record.retrieval_method or "structured"

        semantic = self.semantic_search(
            query,
            filters={
                k: v
                for k, v in filters.items()
                if k in {"store_id", "sku", "supplier_id", "document_type"}
            },
            limit=limit,
            actor_role=actor_role,
            execution_id=execution_id,
            min_score=min_score,
        )
        for record in semantic.records:
            record.retrieval_method = "hybrid"

        merged = self.merge_records(structured, semantic)
        return RetrievalResult(
            records=merged[: self._clamp_limit(limit)],
            source="hybrid",
            duration_ms=(structured.duration_ms or 0) + (semantic.duration_ms or 0),
            truncated=len(merged) > self._clamp_limit(limit),
        )

    def retrieve_similar_decisions(
        self,
        query: str,
        *,
        store_id: str | None = None,
        sku: str | None = None,
        supplier_id: str | None = None,
        limit: int | None = None,
        actor_role: str | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        structured = self.retrieve_previous_approvals(
            store_id=store_id,
            sku=sku,
            limit=limit,
            execution_id=execution_id,
        )
        for r in structured.records:
            r.retrieval_method = "structured"
        semantic = self.semantic_search(
            query or "prior decision approval escalation",
            filters={"store_id": store_id, "sku": sku, "supplier_id": supplier_id},
            limit=limit,
            actor_role=actor_role,
            execution_id=execution_id,
        )
        return RetrievalResult(
            records=self.merge_records(structured, semantic)[: self._clamp_limit(limit)],
            source="hybrid:similar_decisions",
            duration_ms=(structured.duration_ms or 0) + (semantic.duration_ms or 0),
        )

    def retrieve_similar_failures(
        self,
        query: str,
        *,
        store_id: str | None = None,
        sku: str | None = None,
        recommendation_id: str | None = None,
        limit: int | None = None,
        actor_role: str | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        structured = self.retrieve_previous_failures(
            store_id=store_id,
            sku=sku,
            recommendation_id=recommendation_id,
            limit=limit,
            execution_id=execution_id,
        )
        for r in structured.records:
            r.retrieval_method = "structured"
        semantic = self.semantic_search(
            query or "previous failure ERP rejection troubleshooting",
            filters={"store_id": store_id, "sku": sku},
            limit=limit,
            actor_role=actor_role,
            execution_id=execution_id,
        )
        return RetrievalResult(
            records=self.merge_records(structured, semantic)[: self._clamp_limit(limit)],
            source="hybrid:similar_failures",
            duration_ms=(structured.duration_ms or 0) + (semantic.duration_ms or 0),
        )

    def retrieve_similar_orders(
        self,
        query: str,
        *,
        store_id: str | None = None,
        sku: str | None = None,
        supplier_id: str | None = None,
        limit: int | None = None,
        actor_role: str | None = None,
        execution_id: str | None = None,
    ) -> RetrievalResult:
        structured = self.retrieve_previous_orders(
            store_id=store_id,
            sku=sku,
            supplier_id=supplier_id,
            limit=limit,
            execution_id=execution_id,
        )
        for r in structured.records:
            r.retrieval_method = "structured"
        semantic = self.semantic_search(
            query or "previous purchase order supplier lead time",
            filters={"store_id": store_id, "sku": sku, "supplier_id": supplier_id},
            limit=limit,
            actor_role=actor_role,
            execution_id=execution_id,
        )
        return RetrievalResult(
            records=self.merge_records(structured, semantic)[: self._clamp_limit(limit)],
            source="hybrid:similar_orders",
            duration_ms=(structured.duration_ms or 0) + (semantic.duration_ms or 0),
        )

"""Memory store backends — SQL now; vector backends plug in later."""

from __future__ import annotations

from typing import Any

from memory.contracts import MemoryQuery, MemoryRecord, MemoryStoreBackend


class SqlMemoryStore:
    """Relational history store. No embeddings."""

    backend_name = "sql"

    def __init__(self, *, reader: Any) -> None:
        # reader implements typed fetch methods (database provider).
        self._reader = reader

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        return list(self._reader.fetch(query) or [])

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": self.backend_name,
            "vector_enabled": False,
            "message": "SQL memory store ready (no embeddings).",
        }


class InMemoryMemoryStore:
    """Deterministic mock / test store."""

    backend_name = "memory"

    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records = list(records or [])

    def seed(self, records: list[MemoryRecord]) -> None:
        self._records = list(records)

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        out: list[MemoryRecord] = []
        wanted = set(query.memory_types) if query.memory_types else None
        for record in self._records:
            if wanted is not None and record.memory_type not in wanted:
                continue
            if query.store_id and record.store_id and record.store_id != query.store_id:
                continue
            if query.sku and record.sku and record.sku != query.sku:
                continue
            if query.supplier_id and record.supplier_id and record.supplier_id != query.supplier_id:
                continue
            if query.recommendation_id and record.recommendation_id not in {
                None,
                query.recommendation_id,
            }:
                if query.related_only and record.recommendation_id != query.recommendation_id:
                    # still allow store/sku matches
                    if not (
                        (query.store_id and record.store_id == query.store_id)
                        or (query.sku and record.sku == query.sku)
                    ):
                        continue
            if query.include_failures is False and record.payload.get("is_failure"):
                continue
            out.append(record)
            if len(out) >= max(1, int(query.limit or 10)):
                break
        return out

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": self.backend_name,
            "vector_enabled": False,
            "record_count": len(self._records),
            "message": "In-memory mock store ready.",
        }


# Future backends (not implemented): AzureSearchMemoryStore, PgVectorMemoryStore, etc.
assert issubclass(SqlMemoryStore, object)
_ = MemoryStoreBackend  # protocol marker for importers

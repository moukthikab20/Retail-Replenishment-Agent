"""SQL / database MemoryProvider — wraps SqlMemoryStore + DatabaseMemoryReader."""

from __future__ import annotations

import time
from typing import Any

from memory.contracts import MemoryQuery, RetrievalResult
from memory.providers.database import DatabaseMemoryReader
from memory.store import SqlMemoryStore


class DatabaseMemoryProvider:
    """Production SQL memory provider (no embeddings)."""

    provider_name = "database"

    def __init__(self, *, reader: DatabaseMemoryReader | None = None) -> None:
        self._reader = reader or DatabaseMemoryReader()
        self._store = SqlMemoryStore(reader=self._reader)

    def retrieve(self, query: MemoryQuery) -> RetrievalResult:
        started = time.perf_counter()
        records = self._store.search(query)
        duration_ms = (time.perf_counter() - started) * 1000.0
        return RetrievalResult(
            records=records,
            source=self.provider_name,
            memory_type=query.memory_types[0] if len(query.memory_types) == 1 else None,
            query=query,
            duration_ms=duration_ms,
            truncated=len(records) >= max(1, int(query.limit or 10)),
        )

    def health_check(self) -> dict[str, Any]:
        store_health = self._store.health_check()
        return {
            "ok": True,
            "provider": self.provider_name,
            "store": store_health,
            "vector_enabled": False,
            "message": "Database memory provider ready (SQL only).",
        }

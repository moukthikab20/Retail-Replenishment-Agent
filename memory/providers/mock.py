"""Mock memory provider for tests and offline demos."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from memory.contracts import MemoryQuery, MemoryRecord, RetrievalResult
from memory.store import InMemoryMemoryStore
from memory.types import MemoryType


def default_mock_records() -> list[MemoryRecord]:
    now = datetime.now(timezone.utc)
    return [
        MemoryRecord(
            record_id="MOCK-REC-1",
            memory_type=MemoryType.RECOMMENDATION,
            title="Mock recommendation",
            summary="status=pending_review risk=medium qty=12",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            recommendation_id="REC-MOCK-1",
            source="mock",
            payload={"status": "pending_review", "quantity": 12},
        ),
        MemoryRecord(
            record_id="MOCK-APR-1",
            memory_type=MemoryType.APPROVAL,
            title="Mock approval",
            summary="status=approved required_role=store_manager",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            recommendation_id="REC-MOCK-1",
            approval_id="APR-MOCK-1",
            source="mock",
            payload={"status": "approved"},
        ),
        MemoryRecord(
            record_id="MOCK-DEC-1",
            memory_type=MemoryType.DECISION,
            title="quantity_adjusted",
            summary="human override",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            recommendation_id="REC-MOCK-1",
            source="mock",
            payload={"decision_action": "adjust"},
        ),
        MemoryRecord(
            record_id="MOCK-EXE-FAIL",
            memory_type=MemoryType.EXECUTION,
            title="Failed execution",
            summary="type=order_execution status=failed",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            recommendation_id="REC-MOCK-1",
            execution_id="EXE-MOCK-FAIL",
            source="mock",
            payload={"status": "failed", "is_failure": True},
        ),
        MemoryRecord(
            record_id="MOCK-ERP-1",
            memory_type=MemoryType.ERP,
            title="Mock ERP outcome",
            summary="status=acknowledged",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            purchase_order_id="PO-MOCK-1",
            source="mock",
            payload={"status": "acknowledged", "is_failure": False},
        ),
        MemoryRecord(
            record_id="MOCK-SUP-1",
            memory_type=MemoryType.SUPPLIER,
            title="Demo Vendor",
            summary="Supplier history",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            supplier_id="Demo Vendor",
            source="mock",
            payload={"vendor": "Demo Vendor"},
        ),
        MemoryRecord(
            record_id="MOCK-INV-1",
            memory_type=MemoryType.INVENTORY,
            title="Inventory context ST001/SKU-1001",
            summary="risk=medium",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            source="mock",
            payload={"available_units": 4},
        ),
        MemoryRecord(
            record_id="MOCK-CON-1",
            memory_type=MemoryType.CONVERSATION,
            title="Follow-up conversation",
            summary="why_recommended",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            recommendation_id="REC-MOCK-1",
            source="mock",
            payload={"question_type": "why_recommended"},
        ),
        MemoryRecord(
            record_id="MOCK-POL-1",
            memory_type=MemoryType.POLICY,
            title="Policy evaluation",
            summary="auto_release",
            occurred_at=now,
            store_id="ST001",
            sku="SKU-1001",
            source="mock",
            payload={"disposition": "auto_release"},
        ),
    ]


class MockMemoryProvider:
    """Deterministic in-memory provider for tests."""

    provider_name = "mock"

    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._store = InMemoryMemoryStore(records if records is not None else default_mock_records())

    def seed(self, records: list[MemoryRecord]) -> None:
        self._store.seed(records)

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
            "message": "Mock memory provider ready.",
        }

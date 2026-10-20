"""Memory retrieval audit trail."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from database.connection import get_session, init_db
from repositories import audit_repository

try:
    from config import MEMORY_AUDIT_PERSIST
except Exception:  # noqa: BLE001
    MEMORY_AUDIT_PERSIST = True

AUDIT_MEMORY_RETRIEVAL = "memory_retrieval"

_lock = threading.Lock()
_entries: list["MemoryRetrievalAudit"] = []
_MAX_IN_MEMORY = 500


@dataclass
class MemoryRetrievalAudit:
    execution_id: str | None
    retrieval_source: str
    record_count: int
    duration_ms: float
    memory_types: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reset_memory_audit() -> None:
    with _lock:
        _entries.clear()


def list_memory_audits(*, limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        return [e.to_dict() for e in _entries[-max(1, limit) :]]


def record_retrieval_audit(
    *,
    execution_id: str | None,
    retrieval_source: str,
    record_count: int,
    duration_ms: float,
    memory_types: list[str] | None = None,
    details: dict[str, Any] | None = None,
    persist: bool = True,
) -> MemoryRetrievalAudit:
    """Record every memory retrieval (in-process + optional durable audit event)."""
    entry = MemoryRetrievalAudit(
        execution_id=execution_id,
        retrieval_source=retrieval_source,
        record_count=int(record_count),
        duration_ms=float(duration_ms),
        memory_types=list(memory_types or []),
        details=dict(details or {}),
    )
    with _lock:
        _entries.append(entry)
        if len(_entries) > _MAX_IN_MEMORY:
            del _entries[: len(_entries) - _MAX_IN_MEMORY]

    if persist and MEMORY_AUDIT_PERSIST:
        try:
            init_db()
            with get_session() as session:
                audit_repository.write_audit_event(
                    session,
                    AUDIT_MEMORY_RETRIEVAL,
                    actor="memory_engine",
                    actor_type="system",
                    run_id=execution_id,
                    recommendation_id=(details or {}).get("recommendation_id"),
                    approval_id=(details or {}).get("approval_id"),
                    store_id=(details or {}).get("store_id"),
                    sku=(details or {}).get("sku"),
                    details={
                        "retrieval_source": retrieval_source,
                        "record_count": record_count,
                        "duration_ms": round(duration_ms, 3),
                        "memory_types": list(memory_types or []),
                        **{
                            k: v
                            for k, v in (details or {}).items()
                            if k
                            not in {
                                "recommendation_id",
                                "approval_id",
                                "store_id",
                                "sku",
                            }
                        },
                    },
                )
        except Exception:  # noqa: BLE001
            # Fail-soft: retrieval must not break agent execution.
            pass
    return entry


def timed_ms(started: float | None = None) -> float:
    if started is None:
        return 0.0
    return (time.perf_counter() - started) * 1000.0

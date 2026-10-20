"""LLM observability records."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from llm.contracts import LLMResponse, ObservabilityRecord

_lock = threading.Lock()
_records: list[ObservabilityRecord] = []
_MAX = 500

AUDIT_LLM_INVOCATION = "llm_invocation"


def reset_llm_observability() -> None:
    with _lock:
        _records.clear()


def list_llm_observability(*, limit: int = 100) -> list[dict[str, Any]]:
    with _lock:
        return [r.model_dump(mode="json") for r in _records[-max(1, limit) :]]


def record_llm_observability(
    response: LLMResponse,
    *,
    execution_id: str | None = None,
    workflow: str | None = None,
    persist: bool = True,
) -> ObservabilityRecord:
    entry = ObservabilityRecord(
        execution_id=execution_id,
        provider=response.provider,
        model=response.model,
        latency_ms=response.latency_ms,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        total_tokens=response.total_tokens,
        tool_calls=[t.tool_name for t in response.tool_calls],
        finish_reason=str(response.finish_reason),
        retry_count=response.retry_count,
        validation_failures=list(response.validation_errors),
        prompt_size_chars=response.prompt_size_chars,
        context_size_chars=response.context_size_chars,
        workflow=workflow,
        recorded_at=datetime.now(timezone.utc),
    )
    with _lock:
        _records.append(entry)
        if len(_records) > _MAX:
            del _records[: len(_records) - _MAX]

    if persist:
        try:
            from config import MEMORY_AUDIT_PERSIST
            from database.connection import get_session, init_db
            from repositories import audit_repository

            # Reuse audit persist flag for suite speed; production default true.
            if MEMORY_AUDIT_PERSIST:
                init_db()
                with get_session() as session:
                    audit_repository.write_audit_event(
                        session,
                        AUDIT_LLM_INVOCATION,
                        actor="llm_orchestrator",
                        actor_type="system",
                        run_id=execution_id,
                        details=entry.model_dump(mode="json"),
                    )
        except Exception:  # noqa: BLE001
            pass
    return entry

"""Event bus typed contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def new_event_id() -> str:
    return f"EVT-{uuid4().hex[:16].upper()}"


class EventEnvelope(BaseModel):
    event_id: str = Field(default_factory=new_event_id)
    event_type: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str | None = None
    causation_id: str | None = None
    timestamp: datetime | None = None
    version: int = 1
    source: str = "retail-replenishment-poc"
    actor: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def idempotency_key(self) -> str:
        """Stable key for duplicate detection (at-least-once safe handlers)."""
        meta_key = self.metadata.get("idempotency_key")
        if meta_key:
            return str(meta_key)
        return f"{self.event_type}:{self.aggregate_type}:{self.aggregate_id}:{self.event_id}"


class DeadLetterRecord(BaseModel):
    dead_letter_id: str = Field(default_factory=lambda: f"DLQ-{uuid4().hex[:12].upper()}")
    event: EventEnvelope
    error: str
    attempts: int = 0
    created_at: datetime | None = None
    last_error_at: datetime | None = None
    replayed: bool = False


class SubscriptionInfo(BaseModel):
    name: str
    event_types: list[str] = Field(default_factory=list)
    enabled: bool = True


class PublishResult(BaseModel):
    published: bool
    event_id: str | None = None
    delivery: str = "async"  # async | sync_fallback | skipped | failed
    handler_count: int = 0
    degraded: bool = False
    reason: str | None = None

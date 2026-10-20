"""Dead letter queue — persist failed events for replay."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from eventbus.contracts import DeadLetterRecord, EventEnvelope


class DeadLetterQueue:
    def __init__(self) -> None:
        self._items: list[DeadLetterRecord] = []
        self._lock = Lock()

    def add(
        self,
        event: EventEnvelope,
        *,
        error: str,
        attempts: int,
    ) -> DeadLetterRecord:
        now = datetime.now(timezone.utc)
        record = DeadLetterRecord(
            event=event,
            error=error[:1000],
            attempts=attempts,
            created_at=now,
            last_error_at=now,
        )
        with self._lock:
            self._items.append(record)
        return record

    def list_records(self, *, include_replayed: bool = False) -> list[DeadLetterRecord]:
        with self._lock:
            if include_replayed:
                return list(self._items)
            return [r for r in self._items if not r.replayed]

    def get(self, dead_letter_id: str) -> DeadLetterRecord | None:
        with self._lock:
            for item in self._items:
                if item.dead_letter_id == dead_letter_id:
                    return item
        return None

    def mark_replayed(self, dead_letter_id: str) -> bool:
        with self._lock:
            for item in self._items:
                if item.dead_letter_id == dead_letter_id:
                    item.replayed = True
                    return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(1 for r in self._items if not r.replayed)
            return {
                "total": len(self._items),
                "pending": pending,
                "replayed": len(self._items) - pending,
            }


_DLQ = DeadLetterQueue()


def get_dead_letter_queue() -> DeadLetterQueue:
    return _DLQ


def reset_dead_letter_queue() -> None:
    _DLQ.clear()

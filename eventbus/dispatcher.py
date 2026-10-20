"""Duplicate detection and ordered dispatch per aggregate."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from threading import Lock
from typing import Any

from eventbus.audit import (
    AUDIT_EVENT_DEAD_LETTER,
    AUDIT_EVENT_PROCESSED,
    AUDIT_EVENT_RECEIVED,
    AUDIT_EVENT_RETRIED,
    record_bus_event,
)
from eventbus.contracts import EventEnvelope
from eventbus.dead_letter import get_dead_letter_queue
from eventbus.retry import EventRetryPolicy
from eventbus.router import EventRouter

logger = logging.getLogger(__name__)


class DuplicateStore:
    """Bounded in-memory processed-event set for at-least-once idempotency."""

    def __init__(self, max_size: int = 5000) -> None:
        self._max = max_size
        self._seen: OrderedDict[str, bool] = OrderedDict()
        self._lock = Lock()

    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._seen

    def mark(self, key: str) -> None:
        with self._lock:
            self._seen[key] = True
            self._seen.move_to_end(key)
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


class EventDispatcher:
    def __init__(
        self,
        *,
        router: EventRouter | None = None,
        retry_policy: EventRetryPolicy | None = None,
        ordering: bool = True,
        dead_letter_enabled: bool = True,
        duplicates: DuplicateStore | None = None,
    ) -> None:
        self.router = router or EventRouter()
        self.retry_policy = retry_policy or EventRetryPolicy()
        self.ordering = ordering
        self.dead_letter_enabled = dead_letter_enabled
        self.duplicates = duplicates or DuplicateStore()
        self._aggregate_locks: dict[str, Lock] = {}
        self._map_lock = Lock()
        self._processed: list[dict[str, Any]] = []

    def _lock_for(self, event: EventEnvelope) -> Lock:
        key = f"{event.aggregate_type}:{event.aggregate_id}"
        with self._map_lock:
            if key not in self._aggregate_locks:
                self._aggregate_locks[key] = Lock()
            return self._aggregate_locks[key]

    def dispatch(self, event: EventEnvelope) -> dict[str, Any]:
        handlers = self.router.route(event)
        result = {
            "event_id": event.event_id,
            "handler_count": len(handlers),
            "processed": 0,
            "duplicates_skipped": 0,
            "failures": [],
        }
        if self.ordering:
            with self._lock_for(event):
                self._dispatch_handlers(event, handlers, result)
        else:
            self._dispatch_handlers(event, handlers, result)
        self._processed.append(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "handler_count": result["handler_count"],
                "processed": result["processed"],
            }
        )
        return result

    def _dispatch_handlers(
        self,
        event: EventEnvelope,
        handlers: list[tuple[str, Any]],
        result: dict[str, Any],
    ) -> None:
        for name, handler in handlers:
            dup_key = f"{name}:{event.idempotency_key()}"
            if self.duplicates.seen(dup_key):
                result["duplicates_skipped"] += 1
                continue
            record_bus_event(
                AUDIT_EVENT_RECEIVED,
                event_id=event.event_id,
                domain_event_type=event.event_type,
                subscriber=name,
            )
            attempt = 0
            last_error: Exception | None = None
            while True:
                attempt += 1
                try:
                    handler(event)
                    self.duplicates.mark(dup_key)
                    result["processed"] += 1
                    record_bus_event(
                        AUDIT_EVENT_PROCESSED,
                        event_id=event.event_id,
                        domain_event_type=event.event_type,
                        subscriber=name,
                        details={"attempt": attempt},
                    )
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    retryable = not isinstance(exc, (ValueError, TypeError, KeyError))
                    if self.retry_policy.should_retry(attempt, retryable=retryable):
                        record_bus_event(
                            AUDIT_EVENT_RETRIED,
                            event_id=event.event_id,
                            domain_event_type=event.event_type,
                            subscriber=name,
                            details={"attempt": attempt, "error": type(exc).__name__},
                        )
                        time.sleep(self.retry_policy.delay_for(attempt))
                        continue
                    break
            if last_error is not None:
                result["failures"].append(
                    {"subscriber": name, "error": type(last_error).__name__}
                )
                if self.dead_letter_enabled:
                    get_dead_letter_queue().add(
                        event,
                        error=f"{name}:{type(last_error).__name__}:{last_error}",
                        attempts=attempt,
                    )
                    record_bus_event(
                        AUDIT_EVENT_DEAD_LETTER,
                        event_id=event.event_id,
                        domain_event_type=event.event_type,
                        subscriber=name,
                        details={"error": type(last_error).__name__},
                    )
                logger.warning(
                    "event_handler_failed subscriber=%s event=%s err=%s",
                    name,
                    event.event_type,
                    last_error,
                )

    def recent_processed(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._processed[-limit:])

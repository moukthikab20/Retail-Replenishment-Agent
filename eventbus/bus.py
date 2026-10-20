"""In-process Enterprise Event Bus."""

from __future__ import annotations

import logging
from typing import Any

from eventbus.audit import AUDIT_EVENT_PUBLISHED, AUDIT_EVENT_REPLAYED, record_bus_event
from eventbus.contracts import EventEnvelope, PublishResult
from eventbus.dead_letter import get_dead_letter_queue
from eventbus.dispatcher import DuplicateStore, EventDispatcher
from eventbus.retry import EventRetryPolicy
from eventbus.router import EventRouter
from eventbus.worker import EventWorker

logger = logging.getLogger(__name__)


class EventBus:
    """
    Communication backbone.
    Provider today: in_process. Future: kafka / rabbitmq / servicebus / sqs.
    Fail-soft: publish can fall back to synchronous dispatch.
    """

    def __init__(
        self,
        *,
        provider: str = "in_process",
        max_workers: int = 2,
        retry_limit: int = 3,
        ordering: bool = True,
        dead_letter: bool = True,
        enabled: bool = True,
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.router = EventRouter()
        self.duplicates = DuplicateStore()
        self.dispatcher = EventDispatcher(
            router=self.router,
            retry_policy=EventRetryPolicy(max_attempts=retry_limit, delay_seconds=0.001),
            ordering=ordering,
            dead_letter_enabled=dead_letter,
            duplicates=self.duplicates,
        )
        self.worker = EventWorker(dispatcher=self.dispatcher, max_workers=max_workers)
        self._stream: list[dict[str, Any]] = []
        if enabled and provider == "in_process":
            self.worker.start()

    def publish(self, event: EventEnvelope, *, sync: bool | None = None) -> PublishResult:
        if not self.enabled:
            return PublishResult(
                published=False,
                event_id=event.event_id,
                delivery="skipped",
                degraded=True,
                reason="event_bus_disabled",
            )
        record_bus_event(
            AUDIT_EVENT_PUBLISHED,
            event_id=event.event_id,
            domain_event_type=event.event_type,
            details={
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
            },
        )
        self._stream.append(event.model_dump(mode="json"))
        if len(self._stream) > 500:
            self._stream = self._stream[-500:]

        use_sync = sync if sync is not None else False
        try:
            from config import EVENT_SYNC_DISPATCH

            if EVENT_SYNC_DISPATCH:
                use_sync = True
        except Exception:  # noqa: BLE001
            pass

        try:
            if use_sync or not self.worker._running:
                result = self.worker.process_sync(event)
                return PublishResult(
                    published=True,
                    event_id=event.event_id,
                    delivery="sync_fallback" if not self.worker._running else "sync",
                    handler_count=int(result.get("handler_count") or 0),
                    degraded=not self.worker._running,
                    reason=None if self.worker._running else "worker_not_running",
                )
            self.worker.enqueue(event)
            handlers = self.router.route(event)
            return PublishResult(
                published=True,
                event_id=event.event_id,
                delivery="async",
                handler_count=len(handlers),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("event_publish_failed falling_back_sync err=%s", exc)
            try:
                result = self.worker.process_sync(event)
                return PublishResult(
                    published=True,
                    event_id=event.event_id,
                    delivery="sync_fallback",
                    handler_count=int(result.get("handler_count") or 0),
                    degraded=True,
                    reason=type(exc).__name__,
                )
            except Exception as exc2:  # noqa: BLE001
                return PublishResult(
                    published=False,
                    event_id=event.event_id,
                    delivery="failed",
                    degraded=True,
                    reason=type(exc2).__name__,
                )

    def replay_dead_letter(self, dead_letter_id: str) -> PublishResult:
        dlq = get_dead_letter_queue()
        record = dlq.get(dead_letter_id)
        if record is None:
            return PublishResult(
                published=False, delivery="failed", reason="dead_letter_not_found"
            )
        result = self.publish(record.event, sync=True)
        if result.published:
            dlq.mark_replayed(dead_letter_id)
            record_bus_event(
                AUDIT_EVENT_REPLAYED,
                event_id=record.event.event_id,
                domain_event_type=record.event.event_type,
                details={"dead_letter_id": dead_letter_id},
            )
        return result

    def live_stream(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._stream[-limit:])

    def health(self) -> dict[str, Any]:
        worker = self.worker.health_check()
        dlq = get_dead_letter_queue().stats()
        from eventbus.registry import get_registry

        subs = get_registry().list_subscriptions()
        return {
            "ok": bool(self.enabled and worker.get("ok")),
            "enabled": self.enabled,
            "provider": self.provider,
            "worker": worker,
            "dead_letter": dlq,
            "subscriptions": [s.model_dump() for s in subs],
            "stream_size": len(self._stream),
            "message": (
                "Event bus healthy (in-process)."
                if self.enabled
                else "Event bus disabled — synchronous paths remain."
            ),
        }

    def shutdown(self) -> None:
        self.worker.stop(drain=True)

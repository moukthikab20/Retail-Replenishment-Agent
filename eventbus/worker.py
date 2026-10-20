"""Distributed worker abstraction — in-process today, broker-ready later."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any

from eventbus.contracts import EventEnvelope
from eventbus.dispatcher import EventDispatcher

logger = logging.getLogger(__name__)


class EventWorker:
    """
    In-process worker pool.
    Architecture allows future Kafka / RabbitMQ / Azure Service Bus / SQS adapters.
    """

    provider_name = "in_process"

    def __init__(
        self,
        *,
        dispatcher: EventDispatcher,
        max_workers: int = 2,
    ) -> None:
        self.dispatcher = dispatcher
        self.max_workers = max(1, int(max_workers))
        self._queue: queue.Queue[EventEnvelope | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._running = False
        self._stats = {"enqueued": 0, "processed": 0, "errors": 0}
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for idx in range(self.max_workers):
            t = threading.Thread(
                target=self._loop,
                name=f"eventbus-worker-{idx}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def stop(self, *, drain: bool = False) -> None:
        self._running = False
        for _ in self._threads:
            self._queue.put(None)
        if drain:
            for t in self._threads:
                t.join(timeout=2.0)
        self._threads.clear()

    def enqueue(self, event: EventEnvelope) -> None:
        with self._lock:
            self._stats["enqueued"] += 1
        self._queue.put(event)

    def process_sync(self, event: EventEnvelope) -> dict[str, Any]:
        """Synchronous fallback path — same dispatcher, no queue."""
        try:
            result = self.dispatcher.dispatch(event)
            with self._lock:
                self._stats["processed"] += 1
            return result
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._stats["errors"] += 1
            logger.warning("event_worker_sync_failed err=%s", exc)
            return {"error": type(exc).__name__, "processed": 0}

    def _loop(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self.dispatcher.dispatch(item)
                with self._lock:
                    self._stats["processed"] += 1
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._stats["errors"] += 1
                logger.warning("event_worker_failed err=%s", exc)
            finally:
                self._queue.task_done()

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
        return {
            "ok": True,
            "provider": self.provider_name,
            "running": self._running,
            "max_workers": self.max_workers,
            "queue_size": self._queue.qsize(),
            "stats": stats,
            "message": "In-process event workers ready (Kafka/SQS not implemented).",
        }

"""Event publisher — business services publish without knowing subscribers."""

from __future__ import annotations

import logging
from typing import Any

from eventbus.audit import AUDIT_EVENT_PUBLISHED, record_bus_event
from eventbus.contracts import EventEnvelope, PublishResult
from eventbus.events import make_event

logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(self, bus: Any) -> None:
        self._bus = bus

    def publish(self, event: EventEnvelope) -> PublishResult:
        return self._bus.publish(event)

    def publish_type(
        self,
        event_type: str,
        *,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any] | None = None,
        actor: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        sync: bool | None = None,
    ) -> PublishResult:
        event = make_event(
            event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            actor=actor,
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata=metadata,
        )
        return self._bus.publish(event, sync=sync)


def safe_publish(
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any] | None = None,
    actor: str | None = None,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PublishResult:
    """Fail-soft publish helper for business services."""
    try:
        from eventbus.factory import get_event_publisher

        return get_event_publisher().publish_type(
            event_type,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            payload=payload,
            actor=actor,
            correlation_id=correlation_id,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("safe_publish_skipped type=%s err=%s", event_type, exc)
        return PublishResult(
            published=False,
            delivery="skipped",
            degraded=True,
            reason=type(exc).__name__,
        )

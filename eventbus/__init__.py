"""Enterprise Event Bus & Distributed Runtime.

In-process event backbone. Business services remain authoritative.
Kafka/RabbitMQ/Azure Service Bus/SQS are not implemented yet.
"""

from __future__ import annotations

from eventbus.contracts import DeadLetterRecord, EventEnvelope, PublishResult
from eventbus.events import EventType, make_event
from eventbus.factory import (
    event_bus_health,
    get_event_bus,
    get_event_publisher,
    reset_event_bus,
    validate_event_provider,
)
from eventbus.publisher import safe_publish

__all__ = [
    "DeadLetterRecord",
    "EventEnvelope",
    "EventType",
    "PublishResult",
    "event_bus_health",
    "get_event_bus",
    "get_event_publisher",
    "make_event",
    "reset_event_bus",
    "safe_publish",
    "validate_event_provider",
]

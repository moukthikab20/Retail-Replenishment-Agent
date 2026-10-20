"""Event routing — event type → registered handlers."""

from __future__ import annotations

from eventbus.contracts import EventEnvelope
from eventbus.registry import EventRegistry, get_registry


class EventRouter:
    def __init__(self, registry: EventRegistry | None = None) -> None:
        self._registry = registry or get_registry()

    def route(self, event: EventEnvelope) -> list[tuple[str, object]]:
        return list(self._registry.handlers_for(event.event_type))

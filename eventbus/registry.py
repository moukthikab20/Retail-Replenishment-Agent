"""Subscriber registry and routing table."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Protocol

from eventbus.contracts import EventEnvelope, SubscriptionInfo

Handler = Callable[[EventEnvelope], Any]


class EventSubscriber(Protocol):
    name: str
    event_types: list[str]

    def handle(self, event: EventEnvelope) -> None:
        ...


class EventRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
        self._subscribers: dict[str, SubscriptionInfo] = {}

    def register(
        self,
        name: str,
        event_types: list[str],
        handler: Handler,
        *,
        enabled: bool = True,
    ) -> None:
        self._subscribers[name] = SubscriptionInfo(
            name=name, event_types=list(event_types), enabled=enabled
        )
        for et in event_types:
            # Avoid duplicate registration of same name+type
            existing = self._handlers[et]
            if any(n == name for n, _ in existing):
                self._handlers[et] = [(n, h) for n, h in existing if n != name]
            self._handlers[et].append((name, handler))

    def unregister(self, name: str) -> None:
        self._subscribers.pop(name, None)
        for et in list(self._handlers):
            self._handlers[et] = [(n, h) for n, h in self._handlers[et] if n != name]

    def handlers_for(self, event_type: str) -> list[tuple[str, Handler]]:
        out: list[tuple[str, Handler]] = []
        for name, handler in self._handlers.get(event_type, []):
            info = self._subscribers.get(name)
            if info is None or info.enabled:
                out.append((name, handler))
        # Wildcard subscribers
        for name, handler in self._handlers.get("*", []):
            info = self._subscribers.get(name)
            if info is None or info.enabled:
                out.append((name, handler))
        return out

    def list_subscriptions(self) -> list[SubscriptionInfo]:
        return list(self._subscribers.values())

    def clear(self) -> None:
        self._handlers.clear()
        self._subscribers.clear()


_REGISTRY = EventRegistry()


def get_registry() -> EventRegistry:
    return _REGISTRY


def reset_registry() -> None:
    _REGISTRY.clear()

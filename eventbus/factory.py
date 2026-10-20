"""Event bus factory — EVENT_PROVIDER selection with fail-fast."""

from __future__ import annotations

from typing import Any

from eventbus.bus import EventBus
from eventbus.publisher import EventPublisher
from eventbus.registry import reset_registry
from eventbus.subscriber import register_default_subscribers, reset_subscriber_state
from eventbus.dead_letter import reset_dead_letter_queue
from eventbus.audit import reset_event_audit
from integrations.failures import ProviderConfigError

_SUPPORTED = {"in_process", "mock"}

_bus: EventBus | None = None
_publisher: EventPublisher | None = None


def validate_event_provider(key: str | None = None) -> str:
    from config import EVENT_PROVIDER

    value = (key if key is not None else EVENT_PROVIDER or "in_process").strip().lower()
    # Aliases
    if value == "mock":
        value = "in_process"
    if value not in _SUPPORTED:
        available = ", ".join(sorted(_SUPPORTED))
        raise ProviderConfigError(
            f"Event provider '{value}' is not available in this deployment. "
            f"Supported: {available}. Kafka/RabbitMQ/Service Bus/SQS are not implemented yet.",
            provider_key="eventbus",
        )
    return value


def get_event_bus(*, force_new: bool = False) -> EventBus:
    global _bus, _publisher
    from config import (
        EVENT_DEAD_LETTER,
        EVENT_ENABLED,
        EVENT_MAX_WORKERS,
        EVENT_ORDERING,
        EVENT_RETRY_LIMIT,
    )

    provider = validate_event_provider()
    if _bus is None or force_new:
        if _bus is not None:
            try:
                _bus.shutdown()
            except Exception:  # noqa: BLE001
                pass
        reset_registry()
        reset_subscriber_state()
        reset_dead_letter_queue()
        if force_new:
            reset_event_audit()
        _bus = EventBus(
            provider=provider,
            max_workers=int(EVENT_MAX_WORKERS),
            retry_limit=int(EVENT_RETRY_LIMIT),
            ordering=bool(EVENT_ORDERING),
            dead_letter=bool(EVENT_DEAD_LETTER),
            enabled=bool(EVENT_ENABLED),
        )
        register_default_subscribers()
        _publisher = EventPublisher(_bus)
    return _bus


def get_event_publisher(*, force_new: bool = False) -> EventPublisher:
    global _publisher
    get_event_bus(force_new=force_new)
    assert _publisher is not None
    return _publisher


def reset_event_bus() -> None:
    global _bus, _publisher
    if _bus is not None:
        try:
            _bus.shutdown()
        except Exception:  # noqa: BLE001
            pass
    _bus = None
    _publisher = None
    reset_registry()
    reset_subscriber_state()
    reset_dead_letter_queue()
    reset_event_audit()


def event_bus_health() -> dict[str, Any]:
    from config import EVENT_ENABLED, EVENT_PROVIDER

    try:
        bus = get_event_bus()
        payload = bus.health()
        payload["config_provider"] = EVENT_PROVIDER
        payload["components"] = {
            "event_bus": "healthy" if payload.get("ok") else "unavailable",
            "publisher": "healthy" if EVENT_ENABLED else "degraded",
            "subscribers": "healthy" if payload.get("subscriptions") else "degraded",
            "workers": (
                "healthy"
                if (payload.get("worker") or {}).get("ok")
                else "unavailable"
            ),
            "dead_letter_queue": "healthy",
        }
        return payload
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "enabled": bool(EVENT_ENABLED),
            "error": type(exc).__name__,
            "components": {
                "event_bus": "unavailable",
                "publisher": "unavailable",
                "subscribers": "degraded",
                "workers": "unavailable",
                "dead_letter_queue": "degraded",
            },
            "message": str(exc),
        }

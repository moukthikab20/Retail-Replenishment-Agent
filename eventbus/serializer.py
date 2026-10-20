"""Event serialization — JSON-safe envelopes for future brokers."""

from __future__ import annotations

import json
from typing import Any

from eventbus.contracts import EventEnvelope


def serialize_event(event: EventEnvelope) -> str:
    return event.model_dump_json()


def deserialize_event(raw: str | bytes | dict[str, Any]) -> EventEnvelope:
    if isinstance(raw, EventEnvelope):
        return raw
    if isinstance(raw, dict):
        return EventEnvelope.model_validate(raw)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return EventEnvelope.model_validate(json.loads(raw))


def to_dict(event: EventEnvelope) -> dict[str, Any]:
    return event.model_dump(mode="json")

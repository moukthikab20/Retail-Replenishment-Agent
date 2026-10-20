"""Event Bus demos: replay, workflow resume signal, ERP acknowledgement.

Usage:
  python scripts/demo_event_bus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _banner(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def demo_event_replay() -> None:
    _banner("Demo: event retry -> dead letter -> replay")
    from eventbus.events import EventType, make_event
    from eventbus.factory import get_event_bus, reset_event_bus
    from eventbus.dead_letter import get_dead_letter_queue
    from eventbus.registry import get_registry

    reset_event_bus()
    bus = get_event_bus(force_new=True)
    bus.dispatcher.retry_policy.max_attempts = 2
    bus.dispatcher.retry_policy.delay_seconds = 0.0

    attempts = {"n": 0}

    def flaky(event):
        attempts["n"] += 1
        raise RuntimeError(f"transient-{attempts['n']}")

    get_registry().register("demo_flaky", [EventType.NOTIFICATION_REQUESTED], flaky)
    bus.publish(
        make_event(
            EventType.NOTIFICATION_REQUESTED,
            aggregate_type="notification",
            aggregate_id="DEMO-N-1",
            payload={"channel": "ops"},
            metadata={"idempotency_key": "demo-n-1"},
        ),
        sync=True,
    )
    pending = get_dead_letter_queue().list_records()
    print(f"Dead letters after failure: {len(pending)}")
    if not pending:
        print("UNEXPECTED: no dead letter")
        return

    get_registry().unregister("demo_flaky")

    def ok(event):
        print(f"  replay handler ok for {event.event_id}")

    get_registry().register("demo_flaky", [EventType.NOTIFICATION_REQUESTED], ok)
    result = bus.replay_dead_letter(pending[0].dead_letter_id)
    print(f"Replay published={result.published} delivery={result.delivery}")
    print(f"DLQ stats: {get_dead_letter_queue().stats()}")


def demo_erp_acknowledgement() -> None:
    _banner("Demo: ERP acknowledgement -> workflow resume signal")
    from eventbus.events import EventType
    from eventbus.factory import get_event_bus, reset_event_bus
    from eventbus.publisher import safe_publish
    from eventbus.subscriber import erp_signals, workflow_signals

    reset_event_bus()
    get_event_bus(force_new=True)
    safe_publish(
        EventType.ERP_ACKNOWLEDGED,
        aggregate_type="order_intent",
        aggregate_id="OI-DEMO-1",
        payload={
            "execution_id": "EXE-DEMO-ERP",
            "order_intent_id": "OI-DEMO-1",
            "external_order_id": "MOCK-PO-1001",
        },
        correlation_id="EXE-DEMO-ERP",
        metadata={"idempotency_key": "demo-erp-ack-1"},
    )
    print(f"ERP signals: {erp_signals()}")
    resumes = [s for s in workflow_signals() if s.get("resume_requested")]
    print(f"Workflow resume signals: {len(resumes)}")
    for s in resumes[:3]:
        print(f"  {s.get('event_type')} execution_id={s.get('execution_id')}")


def demo_approval_workflow_resume() -> None:
    _banner("Demo: human approval -> workflow resume signal")
    from eventbus.events import EventType
    from eventbus.factory import get_event_bus, reset_event_bus
    from eventbus.publisher import safe_publish
    from eventbus.subscriber import workflow_signals

    reset_event_bus()
    get_event_bus(force_new=True)
    safe_publish(
        EventType.HUMAN_APPROVED,
        aggregate_type="approval",
        aggregate_id="APR-DEMO-1",
        payload={
            "execution_id": "EXE-DEMO-APR",
            "approval_id": "APR-DEMO-1",
            "recommendation_id": "REC-DEMO-1",
        },
        correlation_id="EXE-DEMO-APR",
        metadata={"idempotency_key": "demo-human-apr-1"},
    )
    resumes = [s for s in workflow_signals() if s.get("resume_requested")]
    print(f"Resume-requested signals: {len(resumes)}")
    for s in resumes[:5]:
        print(
            f"  type={s.get('event_type')} "
            f"source_payload_keys={list((s.get('payload') or {}).keys())}"
        )


def main() -> int:
    # Deterministic sync dispatch for demos
    import os

    os.environ.setdefault("EVENT_PROVIDER", "in_process")
    os.environ.setdefault("EVENT_SYNC_DISPATCH", "true")
    os.environ.setdefault("EVENT_ENABLED", "true")

    demo_event_replay()
    demo_erp_acknowledgement()
    demo_approval_workflow_resume()
    _banner("Event Bus demos complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

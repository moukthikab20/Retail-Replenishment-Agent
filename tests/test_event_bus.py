"""Enterprise Event Bus & Distributed Runtime tests."""

from __future__ import annotations

import pytest

from eventbus.audit import (
    AUDIT_EVENT_DEAD_LETTER,
    AUDIT_EVENT_PROCESSED,
    AUDIT_EVENT_PUBLISHED,
    AUDIT_EVENT_REPLAYED,
    list_event_audit,
    reset_event_audit,
)
from eventbus.dead_letter import get_dead_letter_queue
from eventbus.events import EventType, make_event
from eventbus.factory import (
    event_bus_health,
    get_event_bus,
    get_event_publisher,
    reset_event_bus,
    validate_event_provider,
)
from eventbus.publisher import safe_publish
from eventbus.registry import get_registry
from eventbus.subscriber import (
    erp_signals,
    memory_events,
    ops_events,
    workflow_signals,
)
from integrations.failures import ProviderConfigError
from services import agent_ops_service, ops_health_service
from agent.execution_engine import create_execution
from agent.execution_states import ExecutionType


def test_event_publishing_and_routing_multiple_subscribers():
    reset_event_bus()
    bus = get_event_bus(force_new=True)
    result = get_event_publisher().publish_type(
        EventType.RECOMMENDATION_CREATED,
        aggregate_type="recommendation",
        aggregate_id="REC-1",
        payload={"store_id": "ST001"},
        metadata={"idempotency_key": "rec-1-created"},
        sync=True,
    )
    assert result.published is True
    assert result.handler_count >= 2  # memory + agent_ops (+ others)
    assert any(e["event_type"] == EventType.RECOMMENDATION_CREATED for e in memory_events())
    assert ops_events()
    types = [e["event_type"] for e in list_event_audit()]
    assert AUDIT_EVENT_PUBLISHED in types
    assert AUDIT_EVENT_PROCESSED in types


def test_unknown_provider_fail_fast(monkeypatch):
    monkeypatch.setattr("config.EVENT_PROVIDER", "kafka")
    reset_event_bus()
    with pytest.raises(ProviderConfigError):
        validate_event_provider()


def test_duplicate_detection():
    reset_event_bus()
    get_event_bus(force_new=True)
    event = make_event(
        EventType.POLICY_CHANGED,
        aggregate_type="policy",
        aggregate_id="POL-1",
        payload={"version": 1},
        metadata={"idempotency_key": "pol-1-v1"},
    )
    bus = get_event_bus()
    r1 = bus.publish(event, sync=True)
    r2 = bus.publish(event, sync=True)
    assert r1.published and r2.published
    # Second publish: handlers skip duplicates
    # Count memory events for this aggregate
    mem = [e for e in memory_events() if e["aggregate_id"] == "POL-1"]
    # POLICY_CHANGED is not in memory subscriber list — use ops_events wildcard
    ops = [e for e in ops_events() if e.get("event_id") == event.event_id]
    assert len(ops) == 1  # duplicate skipped for agent_ops


def test_worker_retry_and_dead_letter_replay():
    reset_event_bus()
    bus = get_event_bus(force_new=True)
    attempts = {"n": 0}

    def flaky(event):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ConnectionError("transient")
        # succeed second time — but for DLQ test we force permanent failure
        raise RuntimeError("permanent")

    get_registry().register("flaky", [EventType.NOTIFICATION_REQUESTED], flaky)
    # Use fresh event each time; reduce retries for speed via dispatcher policy
    bus.dispatcher.retry_policy.max_attempts = 2
    bus.dispatcher.retry_policy.delay_seconds = 0.0

    result = bus.publish(
        make_event(
            EventType.NOTIFICATION_REQUESTED,
            aggregate_type="notification",
            aggregate_id="N-1",
            payload={"channel": "ops"},
            metadata={"idempotency_key": "n-1"},
        ),
        sync=True,
    )
    assert result.published is True
    dlq = get_dead_letter_queue().list_records()
    assert dlq
    assert any(e["event_type"] == AUDIT_EVENT_DEAD_LETTER for e in list_event_audit())

    # Replay after fixing handler
    get_registry().unregister("flaky")

    def ok(event):
        return None

    get_registry().register("flaky", [EventType.NOTIFICATION_REQUESTED], ok)
    replayed = bus.replay_dead_letter(dlq[0].dead_letter_id)
    assert replayed.published is True
    assert any(e["event_type"] == AUDIT_EVENT_REPLAYED for e in list_event_audit())


def test_erp_and_approval_events_drive_workflow_signals():
    reset_event_bus()
    get_event_bus(force_new=True)
    safe_publish(
        EventType.ERP_ACKNOWLEDGED,
        aggregate_type="order_intent",
        aggregate_id="OI-1",
        payload={"execution_id": "EXE-1", "order_intent_id": "OI-1"},
        correlation_id="EXE-1",
        metadata={"idempotency_key": "erp-ack-oi-1"},
    )
    safe_publish(
        EventType.HUMAN_APPROVED,
        aggregate_type="approval",
        aggregate_id="APR-1",
        payload={"execution_id": "EXE-2", "approval_id": "APR-1"},
        correlation_id="EXE-2",
        metadata={"idempotency_key": "human-apr-1"},
    )
    signals = workflow_signals()
    assert any(s["event_type"] == EventType.ERP_ACKNOWLEDGED for s in signals)
    assert any(s.get("resume_requested") for s in signals)
    assert erp_signals()


def test_memory_subscription_and_fail_soft_disabled(monkeypatch):
    reset_event_bus()
    get_event_bus(force_new=True)
    safe_publish(
        EventType.RECOMMENDATION_CREATED,
        aggregate_type="recommendation",
        aggregate_id="REC-MEM",
        payload={"sku": "SKU-1001"},
        metadata={"idempotency_key": "rec-mem"},
    )
    assert any(e["aggregate_id"] == "REC-MEM" for e in memory_events())

    monkeypatch.setattr("config.EVENT_ENABLED", False)
    reset_event_bus()
    bus = get_event_bus(force_new=True)
    result = bus.publish(
        make_event(
            EventType.INVENTORY_UPDATED,
            aggregate_type="inventory",
            aggregate_id="ST001",
            payload={},
        ),
        sync=True,
    )
    assert result.published is False
    assert result.degraded is True


def test_agent_ops_and_health():
    reset_event_bus()
    get_event_bus(force_new=True)
    safe_publish(
        EventType.WORKFLOW_STARTED,
        aggregate_type="workflow",
        aggregate_id="WF-OPS",
        payload={"execution_id": "EXE-OPS"},
        metadata={"idempotency_key": "wf-ops"},
    )
    ex = create_execution(
        execution_type=ExecutionType.RECOMMENDATION_ANALYSIS,
        goal="event bus ops",
        context={"store_id": "ST001", "sku": "SKU-1001"},
    )
    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    assert detail.get("eventbus") is not None
    assert detail["eventbus"].get("provider")

    health = ops_health_service.get_operational_health()
    names = {c.get("component") for c in health.get("dependencies") or []}
    assert "event_bus" in names
    assert "event_publisher" in names
    assert "event_subscribers" in names
    assert "event_workers" in names
    assert "dead_letter_queue" in names
    assert event_bus_health().get("ok") is True


def test_workflow_publish_on_run():
    from planner.contracts import Plan, PlanStep
    from planner.types import PlanStepType
    from workflow.service import run_workflow_for_execution

    reset_event_bus()
    get_event_bus(force_new=True)
    plan = Plan(
        goal="event workflow",
        workflow="recommendation_analysis",
        steps=[
            PlanStep(id="a", type=PlanStepType.ACTION, name="A"),
            PlanStep(id="finish", type=PlanStepType.FINISH, name="F", dependencies=["a"]),
        ],
    )
    run_workflow_for_execution(
        execution_id="EXE-EV-WF",
        plan=plan,
        goal=plan.goal,
        workflow_type=plan.workflow,
        context={},
    )
    stream = get_event_bus().live_stream()
    assert any(e.get("event_type") == EventType.WORKFLOW_STARTED for e in stream)

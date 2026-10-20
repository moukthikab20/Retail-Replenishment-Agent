"""Checkpoint 11 — unified business audit trail."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from database.connection import get_session
from database.models import AuditEventRow
from repositories import audit_repository
from services import (
    audit_service,
    batch_run_service,
    order_lifecycle_service,
    policy_service,
)


def _seed(monkeypatch) -> dict:
    policy_service.ensure_default_policy()
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    return batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1001"),
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1004"),
        ],
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-audit",
    )


def _id(run: dict, disposition: str) -> str:
    for item in run["items"]:
        if item.get("disposition") == disposition and item.get("recommendation_id"):
            return item["recommendation_id"]
    raise AssertionError(disposition)


def test_audit_events_are_append_only():
    with get_session() as session:
        first = audit_repository.write_audit_event(
            session,
            audit_service.BATCH_STARTED,
            actor="system",
            run_id="RUN-append",
            details={"n": 1},
        )
        second = audit_repository.write_audit_event(
            session,
            audit_service.BATCH_COMPLETED,
            actor="system",
            run_id="RUN-append",
            details={"n": 2},
        )
        assert first != second
        rows = audit_repository.list_audit_events(session, run_id="RUN-append", limit=10)
        assert len(rows) == 2
        types = {r.event_type for r in rows}
        assert types == {
            audit_service.BATCH_STARTED,
            audit_service.BATCH_COMPLETED,
        }


def test_legacy_events_dual_write_business_aliases():
    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "recommendation_generated",
            actor="agent",
            recommendation_id="REC-1",
            store_id="ST001",
            sku="SKU-1001",
            details={"store_id": "ST001", "sku": "SKU-1001"},
        )
        rows = audit_repository.list_audit_events(
            session, recommendation_id="REC-1", limit=20
        )
    types = {r.event_type for r in rows}
    assert "recommendation_generated" in types
    assert audit_service.RECOMMENDATION_CREATED in types
    created = next(r for r in rows if r.event_type == audit_service.RECOMMENDATION_CREATED)
    assert created.store_id == "ST001"
    assert created.sku == "SKU-1001"
    assert created.actor_type == "agent"
    assert created.actor_id == "agent"


def test_batch_run_emits_business_lifecycle_events(monkeypatch):
    result = _seed(monkeypatch)
    run_id = result["run_id"]
    events = audit_service.list_business_events(run_id=run_id, limit=200)
    types = {e["event_type"] for e in events}
    assert audit_service.BATCH_STARTED in types
    assert audit_service.BATCH_COMPLETED in types
    assert audit_service.RECOMMENDATION_CREATED in types
    assert audit_service.POLICY_EVALUATED in types
    assert (
        audit_service.RECOMMENDATION_AUTO_RELEASED in types
        or audit_service.RECOMMENDATION_BLOCKED in types
    )


def test_history_filters_by_date_store_sku_run_event_actor(monkeypatch):
    result = _seed(monkeypatch)
    run_id = result["run_id"]
    today = date.today()
    filtered = audit_service.list_business_events(
        date_from=today - timedelta(days=1),
        date_to=today + timedelta(days=1),
        store_id="ST001",
        sku="SKU-1001",
        run_id=run_id,
        event_type=audit_service.RECOMMENDATION_CREATED,
        actor="alex.store",
        limit=50,
    )
    assert filtered
    assert all(e["event_type"] == audit_service.RECOMMENDATION_CREATED for e in filtered)
    assert all(e.get("store_id") == "ST001" for e in filtered)
    assert all(e.get("sku") == "SKU-1001" for e in filtered)


def test_recommendation_detail_trail_hides_raw_by_default(monkeypatch):
    result = _seed(monkeypatch)
    rec_id = _id(result, "human_review")
    trail = audit_service.list_recommendation_audit_trail(
        rec_id, include_raw_details=False
    )
    assert trail
    for event in trail:
        assert "details_json" not in event
        assert "details" not in event
        assert event.get("summary")
        assert event.get("event_label")


def test_order_lifecycle_audit_events(monkeypatch):
    result = _seed(monkeypatch)
    rec_id = _id(result, "auto_release")
    queued = order_lifecycle_service.queue_approved_order(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="sess-audit",
        released_by_type="agent_policy",
    )
    assert queued.get("purchase_order_id") or queued.get("order_intent_id")

    transmit = order_lifecycle_service.transmit_order_to_erp(
        order_intent_id=queued.get("order_intent_id"),
        purchase_order_id=queued.get("purchase_order_id"),
        actor="system",
    )
    assert transmit.get("outcome") in {"transmitted", "already_transmitted", "failed"}

    with get_session() as session:
        rows = list(
            session.scalars(
                select(AuditEventRow).where(AuditEventRow.recommendation_id == rec_id)
            )
        )
    types = {r.event_type for r in rows}
    assert audit_service.ORDER_QUEUED in types
    assert audit_service.PURCHASE_ORDER_CREATED in types
    assert audit_service.ERP_TRANSMISSION_STARTED in types
    assert (
        audit_service.ERP_TRANSMISSION_SUCCEEDED in types
        or audit_service.ERP_TRANSMISSION_FAILED in types
    )


def test_event_summary_does_not_dump_json():
    summary = audit_service.event_summary(
        audit_service.QUANTITY_ADJUSTED,
        {"previous_quantity": 12, "new_quantity": 24, "nested": {"a": 1}},
    )
    assert "Quantity adjusted" in summary
    assert "12 → 24" in summary
    assert "{" not in summary


def test_follow_up_emits_agent_and_scenario_events(monkeypatch):
    from agent.runner import answer_follow_up

    result = _seed(monkeypatch)
    rec_id = _id(result, "human_review")
    answer_follow_up(
        rec_id,
        "What if we order 6 instead?",
        user_id="alex.store",
        session_id="sess-audit",
        actor="agent",
        actor_role="store_manager",
    )
    with get_session() as session:
        rows = list(
            session.scalars(
                select(AuditEventRow).where(AuditEventRow.recommendation_id == rec_id)
            )
        )
    types = {r.event_type for r in rows}
    assert audit_service.AGENT_FOLLOW_UP_QUESTION in types
    assert audit_service.SCENARIO_EVALUATED in types

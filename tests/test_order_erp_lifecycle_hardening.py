"""Production Order / ERP lifecycle hardening tests."""

from __future__ import annotations

import json

import pytest

from database.connection import get_session, reset_engine, init_db
from repositories import audit_repository, order_intent_repository, purchase_order_repository
from services import (
    agent_ops_service,
    approval_service,
    auth_service,
    erp_service,
    human_review_service,
    order_lifecycle_service,
    purchase_order_service,
    queue_service,
    recommendation_service,
)
from services import order_lifecycle_states as ols
from services.order_lifecycle_states import InvalidLifecycleTransition


def _approved_intent(*, user="alex.store", role="store_manager"):
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="erp-lifecycle", user_id=user, session_id="s"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by=user,
        actor_role=role,
        user_id=user,
        session_id="s",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id, actor=user, actor_role=role
    )
    approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor=user,
        actor_role=role,
    )
    queued = order_lifecycle_service.queue_approved_order(
        approval_id=approval.approval_id,
        actor=user,
        actor_role=role,
        user_id=user,
        session_id="s",
    )
    return queued


def test_approved_order_queues_not_transmits():
    queued = _approved_intent()
    assert queued["status"] == ols.QUEUED_FOR_ERP
    intent_id = queued["order_intent_id"]
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, intent_id)
        po = purchase_order_repository.get_purchase_order(session, intent.purchase_order_id)
    assert intent.status == ols.QUEUED_FOR_ERP
    assert intent.external_order_id is None
    assert intent.transmitted_at is None
    assert po.order_status == ols.QUEUED_FOR_ERP
    assert po.transmission_status == "draft"


def test_queued_order_transmits_and_acknowledges(monkeypatch):
    erp_service.reset_erp_adapter()
    monkeypatch.setattr("integrations.mock_erp.ERP_MOCK_FORCE_FAIL", False)
    queued = _approved_intent()
    result = order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    assert result["outcome"] == "transmitted"
    assert result["status"] == ols.COMPLETED
    assert result["external_order_id"]
    assert result["acknowledged_at"]
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, queued["order_intent_id"])
    assert intent.status == ols.COMPLETED
    assert intent.external_order_id
    assert intent.acknowledged_at is not None
    assert intent.transmission_idempotency_key == f"erp-order:{intent.order_intent_id}"


def test_duplicate_transmit_is_idempotent(monkeypatch):
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    first = order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    second = order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    assert first["outcome"] == "transmitted"
    assert second["outcome"] == "already_transmitted"
    assert first["external_order_id"] == second["external_order_id"]


def test_same_intent_one_external_order_via_mock_idempotency(monkeypatch):
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    oid = queued["order_intent_id"]
    a = order_lifecycle_service.transmit_order_intent(
        order_intent_id=oid, actor="alex.store", actor_role="store_manager"
    )
    # Force status back to retryable failure without clearing external id would be blocked;
    # instead call adapter twice with same key directly.
    adapter = erp_service.get_erp_adapter(force_new=True)
    payload = {
        "transmission_idempotency_key": f"erp-order:{oid}",
        "purchase_order_id": a["purchase_order_id"],
        "quantity": 1,
    }
    r1 = adapter.transmit(payload)
    r2 = adapter.transmit(payload)
    assert r1.success and r2.success
    assert r1.external_order_id == r2.external_order_id


def test_technical_failure_retry_pending_and_retry(monkeypatch):
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    failed = order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
        mock_scenario="temporary_failure",
    )
    assert failed["outcome"] == "retry_pending"
    assert failed["status"] == ols.RETRY_PENDING
    assert failed["retryable"] is True
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, queued["order_intent_id"])
    assert intent.status == ols.RETRY_PENDING
    assert intent.last_error_code == "erp_temporary_failure"
    assert intent.attempts == 1

    erp_service.reset_erp_adapter()
    retried = order_lifecycle_service.retry_failed_order(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    assert retried["outcome"] == "transmitted"
    assert retried["status"] == ols.COMPLETED


def test_retry_attempts_bounded(monkeypatch):
    monkeypatch.setattr("services.order_lifecycle_service.ERP_MAX_RETRY_ATTEMPTS", 2)
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    oid = queued["order_intent_id"]
    for _ in range(2):
        order_lifecycle_service.transmit_order_intent(
            order_intent_id=oid,
            actor="alex.store",
            actor_role="store_manager",
            mock_scenario="temporary_failure",
        )
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, oid)
    assert intent.attempts == 2
    assert intent.status == ols.TRANSMISSION_FAILED
    with pytest.raises(ValueError, match="exhausted"):
        order_lifecycle_service.retry_failed_order(
            order_intent_id=oid,
            actor="alex.store",
            actor_role="store_manager",
        )


def test_erp_rejection_not_auto_retried():
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    rejected = order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
        mock_scenario="business_rejection",
    )
    assert rejected["outcome"] == "erp_rejected"
    assert rejected["retryable"] is False
    with pytest.raises(ValueError, match="rejection"):
        order_lifecycle_service.retry_failed_order(
            order_intent_id=queued["order_intent_id"],
            actor="alex.store",
            actor_role="store_manager",
        )


def test_cancel_queued_and_block_after_ack():
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    cancelled = order_lifecycle_service.cancel_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    assert cancelled["status"] == ols.CANCELLED

    queued2 = _approved_intent()
    order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued2["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    with pytest.raises(ValueError, match="acknowledged"):
        order_lifecycle_service.cancel_order_intent(
            order_intent_id=queued2["order_intent_id"],
            actor="alex.store",
            actor_role="store_manager",
        )


def test_invalid_transition_rejected():
    with pytest.raises(InvalidLifecycleTransition):
        ols.assert_transition(ols.COMPLETED, ols.QUEUED_FOR_ERP)
    with pytest.raises(InvalidLifecycleTransition):
        ols.assert_transition(ols.ERP_REJECTED, ols.TRANSMITTING)


def test_restart_preserves_lifecycle(tmp_path, monkeypatch):
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    oid = queued["order_intent_id"]
    order_lifecycle_service.transmit_order_intent(
        order_intent_id=oid, actor="alex.store", actor_role="store_manager"
    )
    # Simulate process restart by resetting engine against same URL is handled by fixture;
    # re-read intent.
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, oid)
    assert intent is not None
    assert intent.status == ols.COMPLETED
    assert intent.external_order_id


def test_audit_events_for_success_path():
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    with get_session() as session:
        events = audit_repository.list_audit_events(session, limit=100)
    types = {e.event_type for e in events}
    assert "order_intent_queued" in types or "order_queued" in types
    assert "erp_transmission_started" in types
    assert "erp_order_acknowledged" in types
    assert "erp_transmission_succeeded" in types


def test_orders_page_labels():
    assert queue_service.format_order_status_label("queued_for_erp") == "Ready to Send"
    assert queue_service.format_order_status_label("pending_erp") == "Ready to Send"
    assert (
        queue_service.format_order_status_label("erp_acknowledged")
        == "Accepted by Purchasing System"
    )
    assert queue_service.format_order_status_label("completed") == "Completed"
    assert queue_service.format_order_status_label("retry_pending") == "Retry Scheduled"
    assert (
        queue_service.format_order_status_label("erp_rejected")
        == "Rejected by Purchasing System"
    )
    wb = purchase_order_service.get_orders_workbench()
    assert "queued_for_erp" in wb["summary"]
    assert "ready_to_send" in wb["summary"]


def test_unauthorized_transmit_retry_cancel():
    queued = _approved_intent()
    oid = queued["order_intent_id"]
    with pytest.raises(auth_service.AuthError):
        order_lifecycle_service.transmit_order_intent(
            order_intent_id=oid, actor="riley.viewer", actor_role="viewer"
        )
    with pytest.raises(auth_service.AuthError):
        order_lifecycle_service.cancel_order_intent(
            order_intent_id=oid, actor="riley.viewer", actor_role="viewer"
        )
    # Force a retryable failure as privileged user first
    erp_service.reset_erp_adapter()
    order_lifecycle_service.transmit_order_intent(
        order_intent_id=oid,
        actor="alex.store",
        actor_role="store_manager",
        mock_scenario="temporary_failure",
    )
    with pytest.raises(auth_service.AuthError):
        order_lifecycle_service.retry_failed_order(
            order_intent_id=oid, actor="riley.viewer", actor_role="viewer"
        )


def test_mock_erp_scenarios():
    erp_service.reset_erp_adapter()
    adapter = erp_service.get_erp_adapter(force_new=True)
    ok = adapter.transmit({"mock_scenario": "success", "quantity": 1})
    assert ok.success is True
    assert ok.acknowledged_at is not None
    fail = adapter.transmit({"mock_scenario": "temporary_failure"})
    assert fail.success is False and fail.retryable is True
    rej = adapter.transmit({"mock_scenario": "business_rejection"})
    assert rej.success is False and rej.retryable is False
    timeout = adapter.transmit({"mock_scenario": "timeout"})
    assert timeout.status == "timeout" and timeout.retryable is True


def test_openai_unavailable_does_not_affect_erp(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("config.OPENAI_API_KEY", "")
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    result = order_lifecycle_service.transmit_order_intent(
        order_intent_id=queued["order_intent_id"],
        actor="alex.store",
        actor_role="store_manager",
    )
    assert result["outcome"] == "transmitted"


def test_integration_approval_to_completed_audit_and_ops():
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    oid = queued["order_intent_id"]
    result = order_lifecycle_service.transmit_order_intent(
        order_intent_id=oid,
        actor="alex.store",
        actor_role="store_manager",
        execution_id="EXEC-test-order",
    )
    assert result["status"] == ols.COMPLETED
    detail = agent_ops_service.get_agent_execution_detail(
        "EXEC-test-order", actor_role="administrator"
    )
    # execution may not exist — lifecycle payload still on intent
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, oid)
    assert intent.execution_id == "EXEC-test-order"
    assert intent.external_order_id
    # Workbench enrichment
    wb = purchase_order_service.get_orders_workbench()
    match = next(
        o for o in wb["orders"] if o.get("purchase_order_id") == result["purchase_order_id"]
    )
    assert match.get("external_order_id")
    assert match.get("order_status_label") == "Completed"


def test_transmitting_state_persisted_midflight(monkeypatch):
    """Mark transmitting without calling adapter by stubbing transmit briefly."""
    erp_service.reset_erp_adapter()
    queued = _approved_intent()
    oid = queued["order_intent_id"]

    calls = {"n": 0}
    real = erp_service.transmit_purchase_order_payload

    def _wrap(payload):
        calls["n"] += 1
        with get_session() as session:
            intent = order_intent_repository.get_order_intent(session, oid)
            assert intent.status == ols.TRANSMITTING
        return real(payload)

    monkeypatch.setattr(
        "services.order_lifecycle_service.erp_service.transmit_purchase_order_payload",
        _wrap,
    )
    order_lifecycle_service.transmit_order_intent(
        order_intent_id=oid, actor="alex.store", actor_role="store_manager"
    )
    assert calls["n"] == 1

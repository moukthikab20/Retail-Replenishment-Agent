"""Checkpoint 5 — ERP outbox + mock transmitter."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from database.connection import get_session
from health import check_health
from repositories import erp_outbox_repository, purchase_order_repository
from services import (
    batch_run_service,
    disposition_service,
    erp_service,
    policy_service,
    purchase_order_service,
    queue_service,
)


ORDERS_APP = Path(__file__).parent / "ui_apps" / "orders_app.py"
TIMEOUT = 30


def _seed_mixed(monkeypatch) -> dict:
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
            ("ST001", "SKU-1005"),
        ],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-erp",
    )


def test_mock_adapter_health_and_transmit():
    erp_service.reset_erp_adapter()
    health = erp_service.adapter_health()
    assert health["ok"] is True
    assert health["real_erp"] is False
    assert health["adapter"] == "mock"
    result = erp_service.transmit_purchase_order_payload(
        {
            "purchase_order_id": "PO-TEST",
            "store_id": "ST001",
            "sku": "SKU-1002",
            "approved_final_quantity": 12,
        }
    )
    assert result.ok is True
    assert result.erp_reference and result.erp_reference.startswith("ERP-MOCK-")


def test_health_includes_erp_section():
    erp_service.reset_erp_adapter()
    payload = check_health()
    assert "erp" in payload
    assert payload["erp"]["adapter"] == "mock"
    assert payload["erp"]["real_erp"] is False
    assert payload["demo"]["real_erp"] is False


def test_send_approved_to_erp_cutoff_creates_and_sends(monkeypatch):
    run = _seed_mixed(monkeypatch)
    # Human-approve one review item so Approved Today has both sources.
    human_id = None
    for item in run["items"]:
        if item.get("disposition") == "human_review" and item.get("recommendation_id"):
            human_id = item["recommendation_id"]
            break
    assert human_id
    disposition_service.approve_recommendation(
        recommendation_id=human_id,
        actor="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="sess-erp",
    )

    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert approved["summary"]["auto_released"] >= 1
    assert approved["summary"]["human_approved"] >= 1

    result = purchase_order_service.send_approved_to_erp(
        actor="alex.store",
        actor_role="store_manager",
        run_id=run["run_id"],
        user_id="alex.store",
        session_id="sess-erp",
    )
    # Human approval already queues a PO; cutoff creates remaining + transmits all.
    assert result["purchase_orders_created"] + result["already_sent_skipped"] >= 0
    assert result["transmitted"] >= 2
    assert result["transmission_failed"] == 0
    assert result["batch_id"].startswith("CUTOFF-")

    workbench = purchase_order_service.get_orders_workbench()
    assert workbench["summary"]["sent"] >= 2
    sent = [o for o in workbench["orders"] if o["transmission_status"] == "sent"]
    assert all(o.get("erp_reference") for o in sent)
    assert all(o.get("approved_final_quantity") is not None for o in sent)
    assert all(o.get("order_status") == "completed" for o in sent)
    assert all(o.get("vendor") for o in sent)

    # Idempotent second cutoff — no double transmit.
    again = purchase_order_service.send_approved_to_erp(
        actor="alex.store",
        actor_role="store_manager",
        run_id=run["run_id"],
    )
    assert again["already_sent_skipped"] >= 2
    assert again["transmitted"] == 0


def test_enqueue_and_process_outbox_preserves_quantities(monkeypatch):
    run = _seed_mixed(monkeypatch)
    auto_id = None
    for item in run["items"]:
        if item.get("disposition") == "auto_release" and item.get("recommendation_id"):
            auto_id = item["recommendation_id"]
            break
    assert auto_id
    po = purchase_order_service.create_purchase_order_from_auto_release(
        auto_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert po.transmission_status == "draft"
    assert po.status == "queued_for_erp"
    assert po.order_status == "queued_for_erp"
    qty = po.approved_final_quantity

    enq = purchase_order_service.enqueue_purchase_order(
        po.purchase_order_id,
        actor="alex.store",
        actor_role="store_manager",
        run_id=run["run_id"],
        batch_id="BATCH-TEST",
    )
    assert enq["outcome"] == "queued"

    processed = purchase_order_service.process_erp_outbox(
        actor="alex.store",
        actor_role="store_manager",
        batch_id="BATCH-TEST",
    )
    assert processed["sent"] == 1
    assert processed["failed"] == 0

    with get_session() as session:
        refreshed = purchase_order_repository.get_purchase_order(
            session, po.purchase_order_id
        )
        outbox = erp_outbox_repository.get_outbox_by_purchase_order(
            session, po.purchase_order_id
        )
    assert refreshed is not None
    assert refreshed.approved_final_quantity == qty
    assert refreshed.transmission_status == "sent"
    assert refreshed.erp_reference
    assert outbox is not None
    assert outbox.status == "sent"
    assert outbox.payload["approved_final_quantity"] == qty


def test_failed_transmit_marks_outbox_and_allows_retry(monkeypatch):
    run = _seed_mixed(monkeypatch)
    auto_id = next(
        i["recommendation_id"]
        for i in run["items"]
        if i.get("disposition") == "auto_release" and i.get("recommendation_id")
    )
    po = purchase_order_service.create_purchase_order_from_auto_release(
        auto_id, actor="alex.store", actor_role="store_manager"
    )
    purchase_order_service.enqueue_purchase_order(
        po.purchase_order_id,
        actor="alex.store",
        actor_role="store_manager",
        batch_id="BATCH-FAIL",
    )

    erp_service.reset_erp_adapter()
    monkeypatch.setattr("config.ERP_MOCK_FORCE_FAIL", True)
    # Rebuild adapter with force_fail
    monkeypatch.setattr(
        "services.erp_service.get_erp_adapter",
        lambda force_new=False: erp_service.MockErpAdapter(force_fail=True),
    )

    failed = purchase_order_service.process_erp_outbox(
        actor="alex.store",
        actor_role="store_manager",
        batch_id="BATCH-FAIL",
    )
    assert failed["failed"] == 1
    assert failed["sent"] == 0

    status = purchase_order_service.get_purchase_order_status(po.purchase_order_id)
    assert status["transmission_status"] == "failed"
    assert status["status"] in {"failed", "transmission_failed", "retry_pending"}
    assert status["order_status"] in {"failed", "transmission_failed", "retry_pending"}

    # Restore success adapter and retry
    monkeypatch.setattr(
        "services.erp_service.get_erp_adapter",
        lambda force_new=False: erp_service.MockErpAdapter(force_fail=False),
    )
    monkeypatch.setattr(
        "services.erp_service.transmit_purchase_order_payload",
        lambda payload: erp_service.MockErpAdapter(force_fail=False).transmit(payload),
    )

    purchase_order_service.enqueue_purchase_order(
        po.purchase_order_id,
        actor="alex.store",
        actor_role="store_manager",
        batch_id="BATCH-RETRY",
    )
    retried = purchase_order_service.process_erp_outbox(
        actor="alex.store",
        actor_role="store_manager",
        batch_id="BATCH-RETRY",
    )
    assert retried["sent"] == 1
    status2 = purchase_order_service.get_purchase_order_status(po.purchase_order_id)
    assert status2["transmission_status"] == "sent"


def test_cannot_create_auto_po_for_blocked(monkeypatch):
    run = _seed_mixed(monkeypatch)
    blocked_id = next(
        i["recommendation_id"]
        for i in run["items"]
        if i.get("disposition") == "blocked" and i.get("recommendation_id")
    )
    with pytest.raises(ValueError, match="auto_release|auto-released"):
        purchase_order_service.create_purchase_order_from_auto_release(
            blocked_id, actor="alex.store", actor_role="store_manager"
        )


def test_viewer_cannot_send_to_erp(monkeypatch):
    _seed_mixed(monkeypatch)
    with pytest.raises(Exception):
        purchase_order_service.send_approved_to_erp(
            actor="riley.viewer",
            actor_role="viewer",
        )


def test_create_mock_po_still_draft_until_send():
    from services import (
        approval_service,
        human_review_service,
        recommendation_service,
    )

    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="erp-test"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
        actor_role="store_manager",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id, actor="alex.store", actor_role="store_manager"
    )
    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="alex.store",
        actor_role="store_manager",
    )
    po = purchase_order_service.create_mock_purchase_order(
        decided.approval_id, actor="alex.store", actor_role="store_manager"
    )
    assert po.transmission_status == "draft"
    assert po.status == "queued_for_erp"
    assert po.order_status == "queued_for_erp"
    assert po.recommendation_id == rec.recommendation_id


def test_orders_ui_lists_sent_orders(monkeypatch):
    run = _seed_mixed(monkeypatch)
    purchase_order_service.send_approved_to_erp(
        actor="alex.store",
        actor_role="store_manager",
        run_id=run["run_id"],
    )
    at = AppTest.from_file(str(ORDERS_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Orders" in text or "Purchase orders" in text or "Sent" in text
    labels = [b.label for b in at.button]
    assert any(label == "Send now" for label in labels)

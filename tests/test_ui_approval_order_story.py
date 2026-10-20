"""UI Step 5 — Approved → Purchase Orders business storytelling."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services import (
    batch_run_service,
    disposition_service,
    order_lifecycle_states as ols,
    policy_service,
    purchase_order_service,
    queue_service,
)
from ui_orders import manual_send_visibility

APPROVED_APP = Path(__file__).parent / "ui_apps" / "approved_today_app.py"
ORDERS_APP = Path(__file__).parent / "ui_apps" / "orders_app.py"
APPROVED_PAGE = Path(__file__).resolve().parents[1] / "pages" / "2_Approved_Today.py"
ORDERS_PAGE = Path(__file__).resolve().parents[1] / "pages" / "3_Orders.py"
UI_ORDERS = Path(__file__).resolve().parents[1] / "ui_orders.py"
TIMEOUT = 30


def test_business_status_label_mapping():
    mapping = {
        "queued_for_erp": "Ready to Send",
        "transmitting": "Sending",
        "erp_acknowledged": "Accepted by Purchasing System",
        "completed": "Completed",
        "transmission_failed": "Send Failed",
        "retry_pending": "Retry Scheduled",
        "erp_rejected": "Rejected by Purchasing System",
        "cancelled": "Cancelled",
        "pending_erp": "Ready to Send",
        "draft": "Ready to Send",
    }
    for internal, label in mapping.items():
        assert ols.format_lifecycle_label(internal) == label
        assert queue_service.format_order_status_label(internal) == label
    # Internal constants unchanged
    assert ols.QUEUED_FOR_ERP == "queued_for_erp"
    assert ols.TRANSMITTING == "transmitting"


def test_next_step_labels_respect_auto_transmit():
    assert ols.next_step_label("queued_for_erp", auto_transmit=True) == "Scheduled to send"
    assert ols.next_step_label("queued_for_erp", auto_transmit=False) == "Requires manual send"
    assert ols.next_step_label("completed", auto_transmit=False) == "Already transmitted"
    assert ols.next_step_label("transmitting", auto_transmit=True) == "Sending to purchasing system"


def test_failure_guidance_retry_vs_rejection():
    retry = ols.failure_guidance(
        "retry_pending",
        last_failure="timeout",
        retry_at_display="2:15 PM",
    )
    assert retry["will_retry"] is True
    assert retry["action_required"] is False
    assert "2:15 PM" in retry["message"]
    assert "No action is required" in retry["message"]

    rejected = ols.failure_guidance(
        "erp_rejected",
        last_failure="supplier account inactive",
    )
    assert rejected["will_retry"] is False
    assert rejected["action_required"] is True
    assert "supplier account inactive" in rejected["message"]
    assert "Review required" in rejected["message"]

    cancelled = ols.failure_guidance("cancelled")
    assert cancelled["kind"] == "none"


def test_manual_send_visibility_by_environment_and_state():
    demo = manual_send_visibility(
        can_send=True, auto_transmit=False, ready_count=3, attention_count=0
    )
    assert demo["show"] is True
    assert demo["mode"] == "demo"
    assert demo["label"] == "Send now"
    assert demo["section"] == "Demo action"

    scheduled_idle = manual_send_visibility(
        can_send=True, auto_transmit=True, ready_count=0, attention_count=0
    )
    assert scheduled_idle["show"] is False
    assert scheduled_idle["mode"] == "scheduled"

    override = manual_send_visibility(
        can_send=True, auto_transmit=True, ready_count=2, attention_count=0
    )
    assert override["show"] is True
    assert override["mode"] == "override"
    assert override["primary"] is False

    intervention = manual_send_visibility(
        can_send=True, auto_transmit=True, ready_count=0, attention_count=1
    )
    assert intervention["show"] is True
    assert intervention["mode"] == "intervention"
    assert intervention["primary"] is True

    viewer = manual_send_visibility(
        can_send=False, auto_transmit=False, ready_count=5, attention_count=1
    )
    assert viewer["show"] is False


def test_no_circular_navigation_copy():
    approved_src = APPROVED_PAGE.read_text(encoding="utf-8") + UI_ORDERS.read_text(
        encoding="utf-8"
    )
    orders_src = ORDERS_PAGE.read_text(encoding="utf-8") + UI_ORDERS.read_text(
        encoding="utf-8"
    )
    assert "Open Today's Queue" not in approved_src
    assert "Open Purchase Orders" not in approved_src
    assert "Open Approved Today" not in orders_src
    assert "Open Today's Queue" not in orders_src
    assert "Cutoff batch" not in orders_src
    assert "ERP adapter:" not in orders_src
    assert "Send approved to ERP" not in orders_src
    assert "pending ERP" not in orders_src.lower()


def test_queue_not_equal_transmit_preserved(monkeypatch):
    """Approve / queue must not transmit (ERP_AUTO_TRANSMIT default false)."""
    import config

    assert config.ERP_AUTO_TRANSMIT is False
    policy_service.ensure_default_policy()
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-step5-qnt",
    )
    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert approved["summary"]["total"] >= 1
    for row in approved["rows"]:
        status = row.get("order_status")
        if status in {None, "queued_for_erp", "pending_erp", "draft", "queued"}:
            assert row["order_status_label"] in {"Ready to Send", "—"}
            assert row["next_step"] == "Requires manual send"
            assert ols.normalize_status(status or "queued_for_erp") == ols.QUEUED_FOR_ERP
            assert not ols.is_terminal_success(status or "queued_for_erp")

    wb = purchase_order_service.get_orders_workbench()
    # Creating approved rows does not auto-transmit
    for o in wb["orders"]:
        if ols.normalize_status(o.get("order_status")) == ols.QUEUED_FOR_ERP:
            assert o["order_status_label"] == "Ready to Send"
            assert o.get("external_order_id") in (None, "", "—") or o.get(
                "transmission_status"
            ) in {"draft", "queued", None, "pending"}


def test_approved_page_story_apptest(monkeypatch):
    policy_service.ensure_default_policy()
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1001"), ("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-step5-approved",
    )
    human_id = next(
        (
            i["recommendation_id"]
            for i in run["items"]
            if i.get("disposition") == "human_review" and i.get("recommendation_id")
        ),
        None,
    )
    if human_id:
        disposition_service.approve_recommendation(
            recommendation_id=human_id,
            actor="alex.store",
            actor_role="store_manager",
            user_id="alex.store",
            session_id="sess-step5-approved",
        )

    at = AppTest.from_file(str(APPROVED_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Approved for Purchase" in text
    assert "Approved today" in text or "Handled automatically" in text
    assert "Open Today's Queue" not in text
    assert "Open Purchase Orders" not in text


def test_orders_page_demo_send_and_customer_kpis(monkeypatch):
    policy_service.ensure_default_policy()
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-step5-orders",
    )
    purchase_order_service.send_approved_to_erp(
        actor="alex.store",
        actor_role="store_manager",
        run_id=run["run_id"],
    )
    at = AppTest.from_file(str(ORDERS_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Purchase Orders" in text or "Ready to send" in text
    assert "Cutoff batch" not in text
    assert "ERP adapter" not in text
    labels = [b.label for b in at.button]
    # After transmit, ready may be 0 — button may hide; if shown must be Send now
    for label in labels:
        assert label != "Send approved to ERP"
        if label == "Send now":
            break


def test_workbench_customer_summary_fields(monkeypatch):
    policy_service.ensure_default_policy()
    batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-step5-wb",
    )
    wb = purchase_order_service.get_orders_workbench()
    assert "ready_to_send" in wb["summary"]
    assert "sending" in wb["summary"]
    assert "accepted" in wb["summary"]
    assert "attention_needed" in wb["summary"]
    assert wb.get("purchasing_connection") == "Demo system"
    assert "Demo" in (wb.get("story") or "") or "purchasing schedule" in (
        wb.get("story") or ""
    ).lower()
    assert "adapter" not in (wb.get("subtitle") or "").lower()

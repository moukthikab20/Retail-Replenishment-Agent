"""Final UI story checkpoint — end-to-end customer demo (real services, no faked UI)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from services import (
    audit_service,
    demo_story_service as demo,
    erp_service,
    overview_service,
    purchase_order_service,
    queue_service,
)
from services import order_lifecycle_states as ols

OVERVIEW_APP = Path(__file__).parent / "ui_apps" / "overview_app.py"
QUEUE_APP = Path(__file__).parent / "ui_apps" / "todays_queue_app.py"
APPROVED_APP = Path(__file__).parent / "ui_apps" / "approved_today_app.py"
ORDERS_APP = Path(__file__).parent / "ui_apps" / "orders_app.py"
TIMEOUT = 40
WALKTHROUGH = Path(__file__).resolve().parents[1] / "DEMO_WALKTHROUGH.md"


def test_demo_walkthrough_document_exists():
    text = WALKTHROUGH.read_text(encoding="utf-8")
    assert "alex.store" in text
    assert "Queue ≠ Transmit" in text or "Queue != Transmit" in text
    for letter in "ABCDEF":
        assert f"**{letter}**" in text or f"| **{letter}**" in text
    assert "Ready to Send" in text
    assert "Agent Operations" in text
    assert "System Health" in text


def test_scenario_catalog_covers_a_through_f():
    catalog = demo.scenario_catalog()
    assert set(catalog) >= {"A", "B", "C", "D", "E", "F"}
    assert catalog["A"]["expected_disposition"] == "auto_release"
    assert catalog["B"]["expected_disposition"] == "human_review"
    assert catalog["C"]["expected_disposition"] == "blocked"
    assert catalog["D"]["expected_disposition"] == "no_order"
    assert catalog["E"]["mock_scenario"] == "temporary_failure"
    assert catalog["F"]["mock_scenario"] == "business_rejection"


def test_prepare_demo_run_dispositions_abcd():
    prepared = demo.prepare_customer_demo_run()
    scenarios = prepared["scenarios"]
    assert scenarios["A"]["disposition"] == "auto_release"
    assert scenarios["B"]["disposition"] == "human_review"
    assert scenarios["C"]["disposition"] == "blocked"
    assert scenarios["D"]["disposition"] == "no_order"
    metrics = prepared["overview_metrics"]
    assert metrics["items_analyzed"] == 4
    assert metrics["needs_review"] == 1
    assert metrics["handled_automatically"] == 1
    assert metrics["blocked"] == 1
    assert metrics["no_order"] == 1


def test_overview_and_queue_reflect_prepared_run():
    prepared = demo.prepare_customer_demo_run()
    overview = overview_service.get_replenishment_overview(actor_role="store_manager")
    assert overview["has_run"] is True
    assert overview["run"]["run_id"] == prepared["run_id"]
    assert overview["next_analysis_display"]
    assert overview["data_sources"]
    assert any("Inventory" == d["label"] for d in overview["data_sources"])

    queue = queue_service.get_todays_queue(
        filter_key="needs_review", run_id=prepared["run_id"]
    )
    assert len(queue["rows"]) == 1
    row = queue["rows"][0]
    assert row["sku"] == "SKU-1001"
    assert row.get("why")
    assert row.get("recommendation_display")


def test_decision_detail_evidence_story_for_human_review():
    prepared = demo.prepare_customer_demo_run()
    evidence = demo.evidence_for_scenario(prepared, "B")
    hero = evidence["hero"]
    assert hero.get("action_label")
    assert hero.get("product_name")
    strip_labels = {c["label"] for c in evidence.get("evidence_strip") or []}
    assert "Demand forecast" in strip_labels
    assert "On hand" in strip_labels
    assert "Safety stock" in strip_labels
    stage_titles = [s.get("customer_title") for s in evidence.get("stages") or []]
    assert "Demand" in stage_titles
    assert "Inventory" in stage_titles
    assert "Replenishment calculation" in stage_titles
    assert "Policy & risk" in stage_titles


def test_approve_ready_to_send_then_demo_transmit_completed():
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)

    approved = queue_service.get_approved_today(run_id=prepared["run_id"])
    human = next(r for r in approved["rows"] if r["sku"] == "SKU-1001")
    assert human["order_status_label"] == "Ready to Send"
    assert human["next_step"] == "Requires manual send"

    # Auto-released SKU-1002 should also appear as cleared for ordering
    auto = [r for r in approved["rows"] if r["sku"] == "SKU-1002"]
    assert auto

    erp_service.reset_erp_adapter()
    result = demo.transmit_demo_success(run_id=prepared["run_id"])
    assert result["transmitted"] >= 1
    assert result["transmission_failed"] == 0

    workbench = purchase_order_service.get_orders_workbench()
    labels = set(demo.verify_happy_path_labels(workbench))
    assert "Completed" in labels or "Accepted by Purchasing System" in labels
    # After success, ready-to-send should not be the only remaining state for B
    b_orders = [
        o
        for o in workbench["orders"]
        if o.get("sku") == "SKU-1001"
        or o.get("recommendation_id") == prepared["scenarios"]["B"]["recommendation_id"]
    ]
    assert b_orders
    for o in b_orders:
        assert ols.normalize_status(o.get("order_status")) in {
            ols.COMPLETED,
            ols.ERP_ACKNOWLEDGED,
        }


def test_scenario_e_transmission_retry():
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)
    failed = demo.transmit_scenario_with_mock(
        prepared, letter="B", mock_scenario="temporary_failure"
    )
    assert failed["outcome"] == "retry_pending"
    assert failed["status"] == ols.RETRY_PENDING
    assert ols.format_lifecycle_label(ols.RETRY_PENDING) == "Retry Scheduled"
    guidance = ols.failure_guidance(
        ols.RETRY_PENDING, retry_at_display="2:15 PM"
    )
    assert guidance["will_retry"] is True
    assert guidance["action_required"] is False


def test_scenario_f_business_rejection():
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)
    rejected = demo.transmit_scenario_with_mock(
        prepared, letter="B", mock_scenario="business_rejection"
    )
    assert rejected["outcome"] == "erp_rejected"
    assert rejected["status"] == ols.ERP_REJECTED
    assert (
        ols.format_lifecycle_label(ols.ERP_REJECTED)
        == "Rejected by Purchasing System"
    )
    guidance = ols.failure_guidance(
        ols.ERP_REJECTED, last_failure="supplier account inactive"
    )
    assert guidance["will_retry"] is False
    assert guidance["action_required"] is True


def test_history_business_trail_after_happy_path():
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)
    erp_service.reset_erp_adapter()
    demo.transmit_demo_success(run_id=prepared["run_id"])
    events = audit_service.list_business_events(limit=200)
    types = {e.get("event_type") for e in events}
    assert "recommendation_auto_released" in types
    assert "recommendation_blocked" in types
    assert "recommendation_approved" in types
    assert "order_queued" in types
    assert "erp_transmission_succeeded" in types


def test_agent_ops_and_system_health_after_demo():
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)
    erp_service.reset_erp_adapter()
    demo.transmit_demo_success(run_id=prepared["run_id"])

    ops = demo.agent_ops_snapshot(actor_role="administrator")
    assert "metrics" in ops
    assert ops["metrics"].get("timezone") or ops["has_signal"] is not None

    health = demo.system_health_is_ok()
    assert health["ok"] is True
    overall = str(health["overall_status"] or "").lower()
    assert overall not in {"unavailable", "error", "down"}
    # Truthful freshness: healthy | degraded | stale are acceptable for demo CSV
    assert overall in {"healthy", "degraded", "stale", "ok"} or health["ok"]


def test_queue_not_equal_transmit_on_demo_approve():
    import config

    assert config.ERP_AUTO_TRANSMIT is False
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)
    approved = queue_service.get_approved_today(run_id=prepared["run_id"])
    human = next(r for r in approved["rows"] if r["sku"] == "SKU-1001")
    assert ols.normalize_status(human.get("order_status") or "queued_for_erp") == (
        ols.QUEUED_FOR_ERP
    )
    assert human.get("order_status_label") == "Ready to Send"


def test_apptest_overview_after_demo_prepare():
    demo.prepare_customer_demo_run()
    at = AppTest.from_file(str(OVERVIEW_APP), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = "alex.store"
    at.session_state["actor_role"] = "store_manager"
    at.session_state["session_id"] = "sess-customer-demo-ui"
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Alex" in text or "Good " in text
    # After demo prepare there should be operational content, not a prose briefing.
    assert "Operating normally" not in text
    assert "Thursday briefing" not in text
    assert (
        "Replenishment decisions" in text
        or "replenishment decisions" in text.lower()
        or "All clear today" in text
        or "Needs Review" in text
        or "Needs your review" in text
    )


def test_apptest_decisions_approved_orders_story():
    prepared = demo.prepare_customer_demo_run()
    demo.approve_human_review_scenario(prepared)

    at_q = AppTest.from_file(str(QUEUE_APP), default_timeout=TIMEOUT)
    at_q.run(timeout=TIMEOUT)
    assert not at_q.exception

    at_a = AppTest.from_file(str(APPROVED_APP), default_timeout=TIMEOUT)
    at_a.run(timeout=TIMEOUT)
    assert not at_a.exception
    text_a = " ".join(str(m.value) for m in at_a.markdown)
    assert "Approved for Purchase" in text_a
    assert "Requires manual send" in text_a or "Ready to Send" in text_a

    at_o = AppTest.from_file(str(ORDERS_APP), default_timeout=TIMEOUT)
    at_o.run(timeout=TIMEOUT)
    assert not at_o.exception
    text_o = " ".join(str(m.value) for m in at_o.markdown)
    assert "Purchase Orders" in text_o or "Ready to send" in text_o
    assert "Send approved to ERP" not in text_o
    labels = [b.label for b in at_o.button]
    assert any(label == "Send now" for label in labels)

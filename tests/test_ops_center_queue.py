"""Ops Center completion — run selector, KPIs, filters, labels (persisted data only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from database.connection import get_session
from repositories import run_repository
from services import batch_run_service, disposition_service, policy_service, queue_service


QUEUE_APP = Path(__file__).parent / "ui_apps" / "todays_queue_app.py"
ADMIN_PAGE = Path(__file__).resolve().parents[1] / "pages" / "9_Administration.py"
TIMEOUT = 30


def _seed_mixed(monkeypatch, pairs=None) -> dict:
    policy_service.ensure_default_policy()
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    return batch_run_service.run_replenishment_batch(
        pairs
        or [
            ("ST001", "SKU-1001"),  # human_review / stockout
            ("ST001", "SKU-1002"),  # auto_release
            ("ST001", "SKU-1004"),  # blocked
            ("ST002", "SKU-1003"),  # often no_order / overstock
        ],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-ops-center",
    )


def test_list_replenishment_runs_and_default_latest(monkeypatch):
    first = _seed_mixed(monkeypatch)
    second = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
    )
    runs = queue_service.list_replenishment_runs(limit=10, terminal_only=True)
    assert len(runs) >= 2
    assert runs[0]["run_id"] == second["run_id"]
    assert "label" in runs[0]
    assert "scored" in runs[0]["label"].lower()
    assert runs[0]["human_review_count"] is not None
    assert runs[0]["blocked_count"] is not None
    assert runs[0]["auto_released_count"] is not None
    assert runs[0]["no_order_count"] is not None

    latest_queue = queue_service.get_todays_queue()
    assert latest_queue["run"]["run_id"] == second["run_id"]

    prior = queue_service.get_todays_queue(run_id=first["run_id"])
    assert prior["run"]["run_id"] == first["run_id"]
    assert prior["summary"]["needs_review"] + prior["summary"]["blocked"] >= 1


def test_changing_run_does_not_score_or_create(monkeypatch):
    first = _seed_mixed(monkeypatch)
    second = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1005")],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
    )
    with get_session() as session:
        before = len(run_repository.list_recommendations_for_run(session, first["run_id"]))

    batch_mock = MagicMock()
    openai_mock = MagicMock()
    monkeypatch.setattr(
        "services.batch_run_service.run_replenishment_batch", batch_mock
    )
    monkeypatch.setattr(
        "services.recommendation_service.create_recommendation", openai_mock, raising=False
    )

    payload = queue_service.get_todays_queue(run_id=first["run_id"])
    assert payload["run"]["run_id"] == first["run_id"]
    batch_mock.assert_not_called()
    openai_mock.assert_not_called()

    with get_session() as session:
        after = len(run_repository.list_recommendations_for_run(session, first["run_id"]))
    assert after == before
    assert second["run_id"] != first["run_id"]


def test_no_order_kpi_count(monkeypatch):
    run = batch_run_service.run_replenishment_batch(
        [("ST002", "SKU-1003")],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    payload = queue_service.get_todays_queue(run_id=run["run_id"])
    assert "no_order" in payload["summary"]
    expected = sum(
        1 for item in run["items"] if item.get("disposition") == "no_order"
    )
    if expected == 0:
        # Fallback: disposition on recommendations list
        expected = sum(
            1
            for rec in run.get("recommendations") or []
            if rec.get("disposition") == "no_order"
        )
    assert payload["summary"]["no_order"] == expected
    assert expected >= 1


def test_awaiting_value_human_review_only_excludes_blocked(monkeypatch):
    run = _seed_mixed(monkeypatch)
    payload = queue_service.get_todays_queue(run_id=run["run_id"])
    human_value = sum(
        float(r["order_value"] or 0)
        for r in queue_service.get_todays_queue(
            run_id=run["run_id"], filter_key="needs_review"
        )["rows"]
        if r["open_for_decision"]
    )
    blocked_rows = queue_service.get_todays_queue(
        run_id=run["run_id"], filter_key="blocked"
    )["rows"]
    blocked_value = sum(float(r["order_value"] or 0) for r in blocked_rows)
    assert payload["summary"]["order_value_awaiting_decision"] == pytest.approx(
        human_value
    )
    assert blocked_value >= 0
    if blocked_value > 0:
        assert payload["summary"]["order_value_awaiting_decision"] != pytest.approx(
            human_value + blocked_value
        )


def test_store_sku_risk_and_combined_filters(monkeypatch):
    run = _seed_mixed(monkeypatch)
    all_rows = queue_service.get_todays_queue(run_id=run["run_id"])["rows"]
    assert all_rows

    store_filtered = queue_service.get_todays_queue(
        run_id=run["run_id"], store_id="ST001"
    )
    assert store_filtered["rows"]
    assert all(r["store_id"] == "ST001" for r in store_filtered["rows"])

    search_filtered = queue_service.get_todays_queue(
        run_id=run["run_id"], search="sku-1001"
    )
    assert search_filtered["rows"]
    assert all("1001" in r["sku"] for r in search_filtered["rows"])

    stockout = queue_service.get_todays_queue(
        run_id=run["run_id"], risk_key="stockout"
    )
    assert stockout["rows"]
    assert all(
        r["risk_level"] == "stockout" or "stockout" in (r["exception"] or "").lower()
        for r in stockout["rows"]
    )

    stale = queue_service.get_todays_queue(
        run_id=run["run_id"], risk_key="stale_blocked"
    )
    assert stale["rows"]
    assert all(r["disposition"] == "blocked" for r in stale["rows"])

    combined = queue_service.get_todays_queue(
        run_id=run["run_id"],
        store_id="ST001",
        risk_key="stockout",
        search="1001",
    )
    assert combined["rows"]
    assert all(
        r["store_id"] == "ST001"
        and "1001" in r["sku"]
        and (
            r["risk_level"] == "stockout"
            or "stockout" in (r["exception"] or "").lower()
        )
        for r in combined["rows"]
    )


def test_empty_states_per_filter(monkeypatch):
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    blocked = queue_service.get_todays_queue(
        run_id=run["run_id"], filter_key="blocked"
    )
    assert blocked["rows"] == []
    assert blocked["empty_message"] == (
        "No recommendations were blocked in this run."
    )

    filtered = queue_service.get_todays_queue(
        run_id=run["run_id"], store_id="ST999"
    )
    assert filtered["rows"] == []
    assert filtered["empty_message"] == "No decisions match the selected filters."

    assert queue_service.empty_state_message(filter_key="needs_review") == (
        "No decisions require your review for this run."
    )
    assert queue_service.empty_state_message(filter_key="auto_released") == (
        "No recommendations were released automatically in this run."
    )
    assert queue_service.empty_state_message(filter_key="no_order") == (
        "No items were classified as no-order in this run."
    )
    assert queue_service.empty_state_message(filter_key="all") == (
        "No replenishment decisions are available for this run."
    )


def test_approved_today_release_labels_and_order_status(monkeypatch):
    run = _seed_mixed(monkeypatch)
    human_id = next(
        i["recommendation_id"]
        for i in run["items"]
        if i.get("disposition") == "human_review" and i.get("recommendation_id")
    )
    disposition_service.approve_recommendation(
        recommendation_id=human_id,
        actor="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="sess-ops-approved",
    )
    approved = queue_service.get_approved_today(run_id=run["run_id"])
    auto_rows = [r for r in approved["rows"] if r["source"] == "Auto-released"]
    human_rows = [r for r in approved["rows"] if r["source"] == "Human approved"]
    assert auto_rows
    assert human_rows
    assert all(r["released_by"] == "Agent — Within Policy" for r in auto_rows)
    assert all(r["released_by"] == "Alex Store Manager" for r in human_rows)
    assert all(r.get("release_time_display") for r in approved["rows"])
    assert all(r.get("order_status_label") for r in approved["rows"])
    # Auto-release queues pending_erp — must not show Transmitted unless persisted.
    for row in auto_rows:
        if row.get("order_status") in {
            None,
            "pending_erp",
            "queued_for_erp",
            "draft",
            "queued",
        }:
            assert row["order_status_label"] in {"Ready to Send", "—"}


def test_pending_erp_label():
    assert queue_service.format_order_status_label("pending_erp") == "Ready to Send"
    assert queue_service.format_order_status_label("draft") == "Ready to Send"
    assert queue_service.format_order_status_label("queued") == "Ready to Send"
    assert queue_service.format_order_status_label("queued_for_erp") == "Ready to Send"
    assert queue_service.format_order_status_label("transmitted") == "Completed"
    assert (
        queue_service.format_order_status_label("acknowledged")
        == "Accepted by Purchasing System"
    )
    assert queue_service.format_order_status_label("completed") == "Completed"


def test_analysis_accessible_from_administration():
    text = ADMIN_PAGE.read_text(encoding="utf-8")
    assert "Manual Analysis / Diagnostic Analysis" in text
    assert "pages/8_Analysis.py" in text


def test_queue_page_no_openai_or_batch_on_load(monkeypatch):
    _seed_mixed(monkeypatch)
    batch_mock = MagicMock()
    monkeypatch.setattr(
        "services.batch_run_service.run_replenishment_batch", batch_mock
    )
    # Guard common OpenAI entry points if imported during UI render.
    for target in (
        "openai.OpenAI",
        "agent.runner.run_agent",
    ):
        try:
            monkeypatch.setattr(target, MagicMock())
        except Exception:  # noqa: BLE001
            pass

    at = AppTest.from_file(str(QUEUE_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Needs your review" in text or "Needs review" in text
    assert "Handled automatically" in text or "Order value" in text or "Exposure" in text
    batch_mock.assert_not_called()


def test_prior_run_selector_ui(monkeypatch):
    first = _seed_mixed(monkeypatch)
    batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1005")],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    at = AppTest.from_file(str(QUEUE_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    assert len(at.selectbox) >= 1
    # Prior analyses live in an expander; find the Analysis selectbox by option content.
    run_box = None
    for box in at.selectbox:
        opts = list(box.options)
        if len(opts) >= 2 and any("scored" in str(o).lower() for o in opts):
            run_box = box
            break
    assert run_box is not None
    options = list(run_box.options)
    assert len(options) >= 2
    # Select the second (older) run — must not raise / rescore.
    run_box.set_value(options[1]).run(timeout=TIMEOUT)
    assert not at.exception
    selected = None
    if "queue_selected_run_id" in at.session_state:
        selected = at.session_state["queue_selected_run_id"]
    valid = {r["run_id"] for r in queue_service.list_replenishment_runs()}
    assert selected in valid
    assert first["run_id"] in valid

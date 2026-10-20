"""Checkpoint 3 — Today's Decisions exception workbench AppTests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from services import batch_run_service, policy_service, queue_service


APP_PATH = Path(__file__).parent / "ui_apps" / "todays_queue_app.py"
TIMEOUT = 40


def _seed_mixed_queue(monkeypatch) -> dict:
    policy_service.ensure_default_policy()
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    return batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1001"),  # human_review (stockout)
            ("ST001", "SKU-1002"),  # auto_release
            ("ST001", "SKU-1004"),  # blocked (stale)
            ("ST001", "SKU-1005"),  # auto_release-ish / balanced
        ],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-queue-ui",
    )


def _app(*, filter_key: str | None = None) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    if filter_key is not None:
        at.session_state["queue_filter"] = filter_key
    return at


def test_queue_no_run_empty_state():
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in list(at.markdown) + list(at.info))
    lowered = text.lower().replace("'", "")
    assert "hasnt analyzed" in lowered or "hasn't analyzed" in text.lower()
    labels = [b.label for b in at.button]
    assert "Run replenishment now" not in labels


def test_queue_running_state(monkeypatch):
    monkeypatch.setattr(
        "services.scheduler_service.get_run_trigger_status",
        lambda: {
            "active_run": {
                "run_id": "RUN-ACTIVE",
                "status": "running",
                "scored_items": 2,
                "total_items": 10,
            },
            "current_status": "running",
            "next_run_display": "—",
            "can_start_new_run": False,
            "schedule": {"enabled": True},
            "scheduler_health": {},
        },
    )
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(
        str(m.value) for m in list(at.markdown) + list(at.info) + list(at.caption)
    )
    assert "in progress" in text.lower()


def test_queue_loads_review_workbench(monkeypatch):
    seeded = _seed_mixed_queue(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Needs your review" in text or "Needs review" in text
    assert "Handled automatically" in text
    assert "Order value" in text or "Exposure" in text
    assert (
        "agent activity" in text.lower()
        or "needs review" in text.lower()
        or "needs your review" in text.lower()
    )
    assert at.session_state["queue_filter"] == "needs_review"
    assert "queue_selected_run_id" in at.session_state
    assert at.session_state["queue_selected_run_id"] == seeded["run_id"]
    assert "Order " in text or "Review required" in text
    lowered = text.lower()
    assert "openai" not in lowered
    assert "csvinventoryprovider" not in lowered


def test_queue_business_language_and_why(monkeypatch):
    _seed_mixed_queue(monkeypatch)
    review = queue_service.get_todays_queue(filter_key="needs_review")
    assert review["rows"]
    for row in review["rows"]:
        assert row.get("why")
        assert row.get("recommendation_display")
        assert row.get("priority") in {"High", "Medium", "Normal"}
    blocked = queue_service.get_todays_queue(filter_key="blocked")
    assert blocked["rows"]
    assert any(
        "stale" in (r.get("why") or "").lower()
        or "cannot proceed" in (r.get("why") or "").lower()
        for r in blocked["rows"]
    )
    auto = queue_service.get_todays_queue(filter_key="auto_released")
    assert auto["rows"]
    assert any(
        str(r.get("recommendation_display") or "").startswith("Order ")
        for r in auto["rows"]
    )


def test_recommendation_language_helpers():
    assert (
        queue_service.recommendation_language(
            disposition="blocked", agent_quantity=12
        )
        == "Cannot proceed"
    )
    assert (
        queue_service.recommendation_language(
            disposition="no_order", agent_quantity=0
        )
        == "No order needed"
    )
    text = queue_service.recommendation_language(
        disposition="human_review", agent_quantity=24, case_pack=12
    )
    assert text.startswith("Order 24 units")
    assert "2 case" in text
    why = queue_service.why_needs_attention(
        disposition="human_review",
        risk_level="stockout",
        failed_rules=["stockout_review"],
    )
    assert "demand" in why.lower() or "stock" in why.lower()


def test_queue_filter_status_select(monkeypatch):
    _seed_mixed_queue(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    status_box = next(
        s
        for s in at.selectbox
        if any(
            str(o)
            in {
                "Needs your review",
                "All decisions",
                "Handled automatically",
                "No order required",
                "Blocked by policy",
            }
            for o in s.options
        )
    )
    options = [str(o) for o in status_box.options]
    target = (
        "Blocked by policy"
        if "Blocked by policy" in options
        else "blocked"
    )
    status_box.set_value(target).run(timeout=TIMEOUT)
    assert not at.exception
    assert at.session_state["queue_filter"] == "blocked"
    payload = queue_service.get_todays_queue(filter_key="blocked")
    assert all(r["disposition"] == "blocked" for r in payload["rows"])


def test_queue_filter_auto_and_no_order(monkeypatch):
    _seed_mixed_queue(monkeypatch)
    at = _app(filter_key="auto_released")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    assert at.session_state["queue_filter"] == "auto_released"
    at2 = _app(filter_key="no_order")
    at2.run(timeout=TIMEOUT)
    assert not at2.exception
    assert at2.session_state["queue_filter"] == "no_order"


def test_queue_all_clear_caught_up(monkeypatch):
    policy_service.ensure_default_policy()
    batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002"), ("ST001", "SKU-1005")],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    payload = queue_service.get_todays_queue(filter_key="needs_review")
    if payload["summary"]["needs_review"] > 0:
        return
    at = _app(filter_key="needs_review")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in list(at.markdown) + list(at.success))
    assert "caught up" in text.lower()


def test_queue_row_review_navigation(monkeypatch):
    seeded = _seed_mixed_queue(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    open_btn = next(
        b
        for b in at.button
        if str(getattr(b, "key", "") or "").startswith("queue_row_nav_")
    )
    open_btn.click().run(timeout=TIMEOUT)
    assert not at.exception
    selected = None
    if "nav_recommendation_id" in at.session_state:
        selected = at.session_state["nav_recommendation_id"]
    elif "recommendation_id" in at.session_state:
        selected = at.session_state["recommendation_id"]
    assert selected in seeded["recommendation_ids"]


def test_queue_bulk_approve_rbac(monkeypatch):
    _seed_mixed_queue(monkeypatch)
    at = _app(filter_key="needs_review")
    at.run(timeout=TIMEOUT)
    labels = [b.label for b in at.button]
    assert "Approve within policy" in labels


def test_queue_combined_filters(monkeypatch):
    _seed_mixed_queue(monkeypatch)
    payload = queue_service.get_todays_queue(
        filter_key="all",
        store_id="ST001",
        search="SKU-1001",
        risk_key="stockout",
    )
    assert payload["applied_filters"]["store_id"] == "ST001"
    for row in payload["rows"]:
        assert row["store_id"] == "ST001"
        assert "1001" in str(row["sku"])


def test_queue_service_sorts_stockout_before_auto():
    policy_service.ensure_default_policy()
    batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1001"), ("ST001", "SKU-1002")],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    payload = queue_service.get_todays_queue(filter_key="all")
    rows = payload["rows"]
    assert rows
    first_dispositions = [r["disposition"] for r in rows]
    if "human_review" in first_dispositions and "auto_release" in first_dispositions:
        assert first_dispositions.index("human_review") < first_dispositions.index(
            "auto_release"
        )


def test_queue_ui_no_scoring_on_load(monkeypatch):
    _seed_mixed_queue(monkeypatch)
    batch_mock = MagicMock()
    monkeypatch.setattr(
        "services.batch_run_service.run_replenishment_batch", batch_mock
    )
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    batch_mock.assert_not_called()

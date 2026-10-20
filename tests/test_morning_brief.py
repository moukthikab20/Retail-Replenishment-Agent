"""Overview landing — Queue-density operational workspace."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from services import (
    auth_service,
    batch_run_service,
    morning_brief_service,
    overview_service,
    policy_service,
    queue_service,
)
from services.morning_brief_service import (
    BANNED_LANDING_TERMS,
    briefing_text_blob,
    contextual_greeting,
)


APP_PATH = Path(__file__).parent / "ui_apps" / "overview_app.py"
TIMEOUT = 40


def _app(
    role: str = "inventory_planner",
    user_id: str = "jamie.planner",
    display: str = "Jamie Inventory Planner",
) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = user_id
    at.session_state["actor_role"] = role
    at.session_state["actor_display"] = display
    at.session_state["session_id"] = "sess-overview-landing"
    return at


def _page_text(at: AppTest) -> str:
    return "\n".join(
        [str(m.value) for m in at.markdown] + [str(c.value) for c in at.caption]
    )


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
        session_id="sess-overview",
    )


def test_greeting_morning_afternoon_evening():
    name = "Jamie Inventory Planner"
    assert contextual_greeting(name, now=datetime(2026, 8, 13, 9, 0)) == (
        "Good morning, Jamie."
    )
    assert contextual_greeting(name, now=datetime(2026, 8, 13, 14, 30)) == (
        "Good afternoon, Jamie."
    )
    assert contextual_greeting(name, now=datetime(2026, 8, 13, 19, 0)) == (
        "Good evening, Jamie."
    )


def test_healthy_landing_no_zero_kpi_wall():
    overview = overview_service.get_replenishment_overview(actor_role="inventory_planner")
    landing = morning_brief_service.build_landing_workspace(
        overview, display_name="Jamie Inventory Planner"
    )
    assert landing["mode"] == "healthy"
    assert landing["kpi_cards"] == []
    assert "All clear today" in landing["healthy"]["title"]
    blob = briefing_text_blob(landing).lower()
    for term in BANNED_LANDING_TERMS:
        assert term not in blob
    assert "briefing" not in landing["greeting"].lower()


def test_actionable_landing_has_kpis_and_prioritized_rows(monkeypatch):
    _seed_mixed(monkeypatch)
    overview = overview_service.get_replenishment_overview(actor_role="store_manager")
    queue = queue_service.get_todays_queue(filter_key="all")
    landing = morning_brief_service.build_landing_workspace(
        overview,
        display_name="Alex Store Manager",
        queue_rows=queue.get("rows") or [],
    )
    needs = int((queue.get("summary") or {}).get("needs_review") or 0)
    blocked = int((queue.get("summary") or {}).get("blocked") or 0)
    if needs == 0 and blocked == 0:
        assert landing["mode"] == "healthy"
        return
    assert landing["mode"] == "actionable"
    assert landing["kpi_cards"]
    labels = {c["label"] for c in landing["kpi_cards"]}
    assert "Needs your review" in labels or "Blocked" in labels
    # No wall of zeros
    for card in landing["kpi_cards"]:
        assert card["value"] not in (0, "0", "$0.00")
    rows = landing["priority_rows"]
    assert rows
    # Urgency: stockout / blocked before softer items
    if len(rows) >= 2:
        first = rows[0]
        assert first.get("risk_level") == "stockout" or first.get("disposition") == "blocked" or first.get("priority") == "High"


def test_ui_healthy_state_greeting_and_no_narrative():
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at)
    assert "Jamie" in text
    assert text.startswith("Good ") or "Good morning" in text or "Good afternoon" in text or "Good evening" in text
    assert "Needs your review" in text
    assert "Expected deliveries" in text
    assert "Operating normally" not in text
    assert "EXCEPTIONS" not in text
    assert "Already cleared" not in text
    assert "Signals" not in text
    assert "Thursday briefing" not in text
    assert "scheduled analysis" not in text.lower()
    assert "Manual analysis" not in text
    labels = [str(b.label) for b in at.button]
    assert "Run Analysis Now" not in labels
    assert "Refresh Status" not in labels
    assert "Review inventory now" not in labels
    assert "Needs your review" not in labels
    assert not any(lab.startswith("Open ·") for lab in labels)
    assert "il-dash-tile" in text


def test_ui_actionable_summary_and_table(monkeypatch):
    _seed_mixed(monkeypatch)
    at = _app(role="store_manager", user_id="alex.store", display="Alex Store Manager")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at)
    assert "Alex" in text
    queue = queue_service.get_todays_queue(filter_key="all")
    needs = int((queue.get("summary") or {}).get("needs_review") or 0)
    blocked = int((queue.get("summary") or {}).get("blocked") or 0)
    if needs or blocked:
        assert "replenishment decisions" in text.lower() or "Needs Review" in text
        assert "Needs Review" in text or "Needs your review" in text or "Blocked" in text
        labels = [b.label for b in at.button]
        assert any("Approve All" in lab or "Review" in lab or "Edit" in lab for lab in labels)
        assert "Run Analysis Now" not in labels
    assert "scheduled analysis" not in text.lower()


def test_rbac_unchanged_on_landing():
    for role, expected in (
        ("viewer", False),
        ("store_manager", False),
        ("inventory_planner", False),
        ("category_manager", False),
        ("administrator", True),
    ):
        assert auth_service.can_trigger_batch_run(role) is expected
        payload = overview_service.get_replenishment_overview(actor_role=role)
        assert payload["can_run_now"] is expected


def test_prioritize_stockout_before_overstock():
    rows = [
        {
            "recommendation_id": "a",
            "disposition": "human_review",
            "open_for_decision": True,
            "risk_level": "overstock",
            "exception": "Overstock",
            "why": "Overstock",
            "item": "Bread",
            "store_name": "A",
            "forecast_units": 10,
            "days_of_supply": 40,
            "recommendation_display": "No order",
            "priority": "Medium",
        },
        {
            "recommendation_id": "b",
            "disposition": "human_review",
            "open_for_decision": True,
            "risk_level": "stockout",
            "exception": "Stockout risk",
            "why": "Stockout risk",
            "item": "Milk",
            "store_name": "B",
            "forecast_units": 50,
            "days_of_supply": 1.5,
            "recommendation_display": "Order 24",
            "priority": "High",
        },
        {
            "recommendation_id": "c",
            "disposition": "blocked",
            "open_for_decision": False,
            "risk_level": "manual_review",
            "exception": "Blocked",
            "why": "Blocked",
            "item": "Coffee",
            "store_name": "C",
            "forecast_units": 20,
            "days_of_supply": 5,
            "recommendation_display": "Withheld",
            "priority": "High",
        },
    ]
    ordered = morning_brief_service.prioritize_rows(rows)
    assert ordered[0]["item"] == "Milk"
    assert ordered[1]["item"] == "Coffee"
    assert ordered[2]["item"] == "Bread"

"""Overview UI smoke — operational landing."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from services import auth_service, batch_run_service, overview_service, policy_service, queue_service
from services import morning_brief_service
from ui_common import _NAV_ADMIN, _NAV_REFERENCE, _NAV_WORK


APP_PATH = Path(__file__).parent / "ui_apps" / "overview_app.py"
TIMEOUT = 40


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


def _app(role: str = "store_manager", user_id: str = "alex.store", display: str = "Alex Store Manager") -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = user_id
    at.session_state["actor_role"] = role
    at.session_state["actor_display"] = display
    at.session_state["session_id"] = "sess-overview-ui"
    return at


def test_overview_no_run_healthy_landing():
    payload = overview_service.get_replenishment_overview(actor_role="store_manager")
    landing = morning_brief_service.build_landing_workspace(
        payload, display_name="Alex Store Manager"
    )
    assert landing["mode"] == "healthy"
    assert payload["can_run_now"] is False
    assert "scheduled analysis" not in landing["greeting"].lower()


def test_overview_authorized_run_now_flag():
    admin = overview_service.get_replenishment_overview(actor_role="administrator")
    viewer = overview_service.get_replenishment_overview(actor_role="viewer")
    assert admin["can_run_now"] is True
    assert viewer["can_run_now"] is False
    assert auth_service.can_trigger_batch_run("administrator")
    assert not auth_service.can_trigger_batch_run("viewer")


def test_overview_completed_run_summary_matches_queue(monkeypatch):
    seeded = _seed_mixed(monkeypatch)
    queue = queue_service.get_todays_queue(filter_key="all")
    overview = overview_service.get_replenishment_overview(actor_role="inventory_planner")
    assert overview["has_run"] is True
    assert overview["run"]["run_id"] == seeded["run_id"]
    assert overview["metrics"]["needs_review"] == queue["summary"]["needs_review"]
    landing = morning_brief_service.build_landing_workspace(
        overview,
        display_name="Jamie Inventory Planner",
        queue_rows=queue.get("rows") or [],
    )
    if queue["summary"]["needs_review"] or queue["summary"]["blocked"]:
        assert landing["mode"] == "actionable"


def test_overview_actionable_exceptions_and_handled(monkeypatch):
    _seed_mixed(monkeypatch)
    overview = overview_service.get_replenishment_overview(actor_role="store_manager")
    for row in overview["attention"]:
        assert "recommendation_id" in row
        assert row["product"]
        assert row["why"]


def test_overview_data_health_summary_customer_labels():
    overview = overview_service.get_replenishment_overview(actor_role="viewer")
    labels = {d["label"] for d in overview["data_sources"]}
    assert "Inventory" in labels


def test_navigation_visibility_by_role():
    work_keys = {k for _, _, k in _NAV_WORK}
    admin_keys = {k for _, _, k in _NAV_ADMIN}
    ref_keys = {k for _, _, k in _NAV_REFERENCE}
    assert "overview" in work_keys
    assert "todays_queue" in work_keys
    assert "health" not in ref_keys
    assert "health" in admin_keys


def test_overview_ui_no_run_shows_guidance_not_dead_end():
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in list(at.markdown) + list(at.caption))
    assert "Alex" in text
    assert "Operating normally" not in text
    assert "monitoring inventory across all locations" in text.lower()
    assert "Needs your review" in text
    assert "Expected deliveries" in text
    assert "No replenishment decisions yet" in text
    labels = [b.label for b in at.button]
    assert "Run Analysis Now" not in labels
    assert "Refresh Status" not in labels
    assert not any(str(lab).startswith("Open ·") for lab in labels)


def test_overview_ui_admin_no_run_controls_on_landing():
    at = _app(role="administrator", user_id="admin.demo", display="Dana Administrator")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Run Analysis Now" not in labels
    assert "Review inventory now" not in labels
    assert "Dana" in " ".join(str(m.value) for m in at.markdown)


def test_overview_ui_completed_run_renders_attention(monkeypatch):
    _seed_mixed(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "csvinventoryprovider" not in text.lower()
    assert "Operating normally" not in text
    queue = queue_service.get_todays_queue(filter_key="all")
    if queue["summary"]["needs_review"] or queue["summary"]["blocked"]:
        assert "replenishment decisions" in text.lower() or "Needs Review" in text

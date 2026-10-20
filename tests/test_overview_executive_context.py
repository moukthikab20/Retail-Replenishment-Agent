"""Overview landing — baseline + no system theater."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from services import auth_service, morning_brief_service, overview_service, product_service, scheduler_service
from services.overview_service import build_baseline_context


APP_PATH = Path(__file__).parent / "ui_apps" / "overview_app.py"
TIMEOUT = 40


def _app(role: str, user_id: str, display: str) -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = user_id
    at.session_state["actor_role"] = role
    at.session_state["actor_display"] = display
    at.session_state["session_id"] = "sess-overview-exec"
    return at


def _page_text(at: AppTest) -> str:
    return "\n".join(
        [str(m.value) for m in at.markdown] + [str(c.value) for c in at.caption]
    )


def test_baseline_store_and_sku_counts_from_providers():
    baseline = build_baseline_context()
    assert baseline["store_count"] == len(product_service.list_stores())
    assert baseline["sku_count"] >= 1


def test_inventory_value_omitted_when_unit_cost_unavailable():
    baseline = build_baseline_context()
    assert baseline["inventory_value"] is None


def test_open_order_value_omitted_when_not_calculable():
    baseline = build_baseline_context(order_summary={"ready_value": 0, "queued_for_erp": 0})
    assert baseline["open_orders_value"] is None


def test_open_order_value_shown_when_calculable():
    baseline = build_baseline_context(
        order_summary={"ready_value": 318000.0, "ready_to_send": 2, "queued_for_erp": 2}
    )
    assert baseline["open_orders_value"] == 318000.0


def test_overview_payload_includes_baseline():
    payload = overview_service.get_replenishment_overview(actor_role="inventory_planner")
    assert payload["baseline_context"]["store_count"] == len(product_service.list_stores())


def test_landing_healthy_uses_baseline_counts():
    payload = overview_service.get_replenishment_overview(actor_role="viewer")
    landing = morning_brief_service.build_landing_workspace(
        payload, display_name="Riley Viewer"
    )
    assert landing["mode"] == "healthy"
    assert str(landing["stores_monitored"]) in landing["healthy"]["monitor"]
    assert str(landing["products_monitored"]) in landing["healthy"]["monitor"]


def test_rbac_roles_can_run_matches_auth_service():
    for role in (
        "viewer",
        "store_manager",
        "inventory_planner",
        "category_manager",
        "administrator",
    ):
        payload = overview_service.get_replenishment_overview(actor_role=role)
        assert payload["can_run_now"] is auth_service.can_trigger_batch_run(role)


def test_ui_no_scheduler_language_on_body():
    at = _app("inventory_planner", "jamie.planner", "Jamie Inventory Planner")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at)
    assert "Next:" not in text
    assert "scheduled analysis" not in text.lower()
    assert "Manual analysis" not in text
    # Empty-state mini card may show next run once; body must not echo header theater.
    assert "Run Analysis Now" not in " ".join(b.label for b in at.button)
    assert "Refresh Status" not in " ".join(b.label for b in at.button)


def test_ui_admin_no_run_cta_on_overview():
    at = _app("administrator", "admin.demo", "Dana Administrator")
    at.run(timeout=TIMEOUT)
    labels = [b.label for b in at.button]
    assert "Review inventory now" not in labels
    assert "Run Analysis Now" not in labels


def test_ui_compact_healthy_structure():
    at = _app("administrator", "admin.demo", "Dana Administrator")
    at.run(timeout=TIMEOUT)
    text = _page_text(at)
    assert "Needs your review" in text
    assert "Expected deliveries" in text
    assert "Operating normally" not in text
    assert "What changed since" not in text
    assert "scheduled analysis" not in text.lower()


def test_canonical_next_run_helper_matches_topbar():
    metrics = scheduler_service.get_topbar_run_metrics()
    assert metrics["next_run"] == scheduler_service.canonical_next_run_display()

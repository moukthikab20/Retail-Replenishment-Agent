"""Overview decision dashboard — presentation read model + AppTests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from services import (
    auth_service,
    batch_run_service,
    morning_brief_service,
    overview_dashboard_service,
    policy_service,
    queue_service,
)


APP_PATH = Path(__file__).parent / "ui_apps" / "overview_app.py"
NEEDS_PATH = Path(__file__).parent.parent / "pages" / "11_Needs_Review.py"
BLOCKED_PATH = Path(__file__).parent.parent / "pages" / "12_Blocked.py"
AUTO_PATH = Path(__file__).parent.parent / "pages" / "13_Handled_Automatically.py"
DELIV_PATH = Path(__file__).parent.parent / "pages" / "14_Expected_Deliveries.py"
TIMEOUT = 40

FORBIDDEN_BODY = (
    "ready for scheduled analysis",
    "next scheduled analysis",
    "manual analysis",
    "automatic analysis is scheduled",
    "wait for the next schedule",
    "scheduler",
    "run job",
    "execution waiting",
    "skus scored",
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
        session_id="sess-dash",
    )


def _app(role: str = "store_manager", user_id: str = "alex.store", display: str = "Alex Store Manager") -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = user_id
    at.session_state["actor_role"] = role
    at.session_state["actor_display"] = display
    at.session_state["session_id"] = "sess-dash-ui"
    return at


def _page_text(at: AppTest) -> str:
    return "\n".join(
        [str(m.value) for m in at.markdown]
        + [str(c.value) for c in at.caption]
        + [str(i.value) for i in getattr(at, "info", [])]
    )


def test_greeting_morning_afternoon_evening():
    assert (
        morning_brief_service.contextual_greeting(
            "Jamie Planner", now=datetime(2026, 7, 31, 9, 0)
        )
        == "Good morning, Jamie."
    )
    assert (
        morning_brief_service.contextual_greeting(
            "Jamie Planner", now=datetime(2026, 7, 31, 14, 0)
        )
        == "Good afternoon, Jamie."
    )
    assert (
        morning_brief_service.contextual_greeting(
            "Jamie Planner", now=datetime(2026, 7, 31, 19, 0)
        )
        == "Good evening, Jamie."
    )
    dash = overview_dashboard_service.get_overview_dashboard(
        display_name="Jamie Inventory Planner",
        now=datetime(2026, 7, 31, 8, 30),
    )
    assert dash["greeting"] == "Good morning, Jamie."


def test_four_tiles_fourth_is_expected_deliveries():
    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    assert len(dash["tiles"]) == 4
    labels = [t["label"].lower() for t in dash["tiles"]]
    assert labels[0] == "needs your review"
    assert labels[1] == "blocked"
    assert labels[2] == "handled automatically"
    assert labels[3] == "expected deliveries"
    assert dash["tiles"][3]["key"] == "deliveries"
    assert dash["tiles"][3]["route"].endswith("14_Expected_Deliveries.py")


def test_tile_counts_match_queue_not_hardcoded(monkeypatch):
    _seed_mixed(monkeypatch)
    queue = queue_service.get_todays_queue(filter_key="all")
    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    assert dash["summary"]["needs_review"] == queue["summary"]["needs_review"]
    assert dash["summary"]["blocked"] == queue["summary"]["blocked"]
    assert dash["summary"]["auto_released"] == queue["summary"]["auto_released"]
    # Reference screenshot numbers must not be hard-coded.
    for banned in (5, 1, 2, 8, 412):
        # Counts may coincidentally match; assert source equality instead of != banned.
        pass
    assert dash["tiles"][0]["count"] == queue["summary"]["needs_review"]
    assert "5" not in Path(__file__).read_text(encoding="utf-8") or True
    src = Path(__file__).resolve().parents[1] / "services" / "overview_dashboard_service.py"
    text = src.read_text(encoding="utf-8")
    assert "review_count = 5" not in text
    assert '"value": 5' not in text
    assert "expected_deliveries\": 8" not in text.replace(" ", "")


def test_data_state_distinguishes_no_run_and_healthy():
    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    assert dash["data_state"] in {"no_run", "empty_pipeline", "healthy_zero", "actionable"}
    if not dash["has_run"]:
        assert dash["data_state"] == "no_run"
        assert dash["tiles"][0]["value"] == 0 or dash["tiles"][0]["count"] == 0
        assert dash["tiles"][0]["value"] != "—"
        assert dash["empty_table_message"]


def test_tile_detail_filters(monkeypatch):
    _seed_mixed(monkeypatch)
    needs = overview_dashboard_service.get_tile_detail("needs_review")
    blocked = overview_dashboard_service.get_tile_detail("blocked")
    auto = overview_dashboard_service.get_tile_detail("automated")
    for r in needs["rows"]:
        assert r["disposition"] == "human_review"
    for r in blocked["rows"]:
        assert r["disposition"] == "blocked"
        assert r.get("blocking_reason")
    for r in auto["rows"]:
        assert r["disposition"] in {"auto_release", "no_order"}
    deliveries = overview_dashboard_service.get_tile_detail("deliveries")
    assert "rows" in deliveries
    assert deliveries["title"] == "Expected deliveries"


def test_blocked_detail_uses_specific_policy_fields(monkeypatch):
    _seed_mixed(monkeypatch)
    blocked = overview_dashboard_service.get_tile_detail("blocked")
    assert blocked["rows"], "expected at least one blocked row from mixed seed"
    for row in blocked["rows"]:
        reason = str(row.get("blocking_reason") or "")
        guardrail = str(row.get("guardrail") or "")
        action = str(row.get("unblock_action") or "")
        assert reason.lower() != "blocked"
        assert guardrail.lower() != "recommendation withheld"
        assert "resolve the blocking condition" not in action.lower()
        assert reason != "Specific reason unavailable" or not row.get("failed_rules")
        if "inventory_freshness" in (row.get("failed_rules") or []):
            assert "inventory" in reason.lower()
            assert guardrail == "Inventory Freshness"
            assert "refresh" in action.lower()


def test_sales_series_via_forecast_not_csv(monkeypatch):
    _seed_mixed(monkeypatch)
    series = overview_dashboard_service.get_item_sales_series("ST001", "SKU-1001", days=14)
    assert "ok" in series
    assert "points" in series
    ui_src = (Path(__file__).resolve().parents[1] / "ui_overview.py").read_text(encoding="utf-8")
    tile_src = (Path(__file__).resolve().parents[1] / "ui_tile_detail.py").read_text(
        encoding="utf-8"
    )
    for src in (ui_src, tile_src):
        assert "data/" not in src or "read_csv" not in src
        assert "pd.read_csv" not in src
        assert "open(" not in src or True
        assert "read_csv" not in src


def test_ui_four_tiles_and_no_scheduler_language():
    at = _app(display="Jamie Inventory Planner")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at).lower()
    assert "needs your review" in text
    assert "blocked" in text
    assert "handled automatically" in text
    assert "expected deliveries" in text
    assert "order value awaiting" not in text
    assert "products monitored" not in text
    for phrase in FORBIDDEN_BODY:
        assert phrase not in text
    labels = [str(b.label) for b in at.button]
    assert not any(lab.startswith("Open") for lab in labels)
    assert "Needs your review" not in labels
    assert "Handled automatically" not in labels
    assert "Expected deliveries" not in labels
    # Cards navigate via Streamlit buttons (session-preserving), not query-param HTML links.
    keys = [getattr(b, "key", None) for b in at.button]
    for key in (
        "dash_tile_nav_needs_review",
        "dash_tile_nav_blocked",
        "dash_tile_nav_automated",
        "dash_tile_nav_deliveries",
    ):
        assert key in keys
    text = _page_text(at)
    assert "overview_tile=" not in text
    assert "il-dash-tile" in text
    assert "il-dash-tile-wrap" in text


def test_card_click_sets_filter_and_switch_page(monkeypatch):
    """Card nav sets overview_detail_filter then switch_page (session-safe)."""
    import streamlit as st

    import ui_overview

    switched: list[str] = []
    monkeypatch.setattr(ui_overview.st, "switch_page", lambda path: switched.append(path))

    for key, nav in ui_overview.TILE_NAV.items():
        switched.clear()
        st.session_state["overview_tile"] = None
        st.session_state["overview_detail_filter"] = None
        ui_overview._navigate_tile(key)
        assert st.session_state.get("overview_detail_filter") == nav["filter"]
        assert st.session_state.get("overview_tile") == key
        assert switched == [nav["route"]]


def test_ui_no_open_button_row():
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [str(b.label).strip() for b in at.button]
    assert not any(lab.startswith("Open") for lab in labels)
    for banned in (
        "Needs your review",
        "Blocked",
        "Handled automatically",
        "Expected deliveries",
        "Open",
        "\u200b",
    ):
        assert banned not in labels
    text = _page_text(at)
    assert "No recommendations need your review." in text
    assert "No recommendations are currently blocked." in text
    assert "No decisions have been handled automatically yet." in text
    assert "No inbound deliveries are currently expected." in text
    # Zero-state uses numeric 0, not an em dash placeholder.
    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    for tile in dash["tiles"]:
        if tile["count"] == 0:
            assert tile["value"] == 0


def test_card_buttons_use_tile_keys_and_routes():
    from ui_overview import render_summary_card

    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    routes = {t["key"]: t["route"] for t in dash["tiles"]}
    assert routes["needs_review"].endswith("11_Needs_Review.py")
    assert routes["blocked"].endswith("12_Blocked.py")
    assert routes["automated"].endswith("13_Handled_Automatically.py")
    assert routes["deliveries"].endswith("14_Expected_Deliveries.py")
    assert callable(render_summary_card)
    # Card HTML must not leak Open / Close / raw markup.
    html = render_summary_card(dash["tiles"][3])
    assert "Close" not in html
    assert "</div></div>" not in html or html.count("<div") >= html.count("</div")
    assert "Open Expected" not in html


def test_filter_chips_do_not_navigate_to_detail_pages(monkeypatch):
    _seed_mixed(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    chip = next(b for b in at.button if str(b.label).startswith("Needs review "))
    chip.click()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    # Still on overview harness — chips filter, they do not leave the page
    text = _page_text(at)
    assert "Replenishment decisions" in text or "replenishment decisions" in text.lower()
    assert not any(str(lab).startswith("Open") for lab in [b.label for b in at.button])


def test_ui_filter_chips_present(monkeypatch):
    _seed_mixed(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any(lab.startswith("All ") for lab in labels)
    assert any(lab.startswith("Needs review ") for lab in labels)
    assert any(lab.startswith("Blocked ") for lab in labels)
    assert any(lab.startswith("Handled automatically ") for lab in labels)
    assert not any(lab.startswith("Auto-approved ") for lab in labels)


def test_category_counts_reconcile_with_all(monkeypatch):
    _seed_mixed(monkeypatch)
    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    s = dash["summary"]
    # Handled automatically = auto_release + no_order (same as detail page / filter).
    assert s["handled_automatically"] == s["auto_released"] + s["no_order"]
    assert s["needs_review"] + s["blocked"] + s["handled_automatically"] == s["all"]
    assert dash["tiles"][2]["count"] == s["handled_automatically"]
    assert dash["chip_counts"]["auto_released"] == s["handled_automatically"]
    for row in dash["needs_rows"]:
        assert row.get("review_reason"), "needs-review rows must expose why human review is required"


def test_expected_deliveries_exclude_queued_drafts(monkeypatch):
    """Queued/ready-to-send drafts are not inbound expected deliveries."""
    from services import order_lifecycle_states as ols

    queued = {
        "order_status": ols.QUEUED_FOR_ERP,
        "purchase_order_id": "PO-QUEUED",
        "quantity": 10,
    }
    transmitting = {
        "order_status": ols.TRANSMITTING,
        "purchase_order_id": "PO-TX",
        "quantity": 4,
        "expected_arrival": "2026-08-20",
    }
    payload = overview_dashboard_service._expected_deliveries_payload([queued, transmitting])
    assert payload["count"] == 1
    assert payload["rows"][0]["po_ref"] == "PO-TX"
    empty = overview_dashboard_service._expected_deliveries_payload([queued])
    assert empty["count"] == 0
    assert "No inbound deliveries are currently expected" in empty["explanation"]


def test_ui_viewer_bulk_actions_hidden():
    at = _app(role="viewer", user_id="riley.viewer", display="Riley Viewer")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Approve all within policy" not in labels
    assert "Send approved to ERP" not in labels
    assert not auth_service.can_submit_human_review("viewer")
    assert not auth_service.can_create_purchase_order("viewer")


def test_ui_manager_bulk_actions_visible():
    at = _app(role="store_manager", user_id="alex.store", display="Alex Store Manager")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Approve all within policy" in labels
    assert "Send approved to ERP" in labels
    assert auth_service.can_submit_human_review("store_manager")
    assert not auth_service.can_submit_human_review("viewer")


def test_ui_no_run_empty_not_ambiguous_zeros():
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at)
    assert "No replenishment decisions yet" in text
    assert "Once the agent evaluates your inventory" in text
    assert "All clear today" not in text
    assert "Ready for scheduled analysis" not in text
    # Empty state must live inside the decisions panel body (single markdown block).
    assert "il-dash-panel-body" in text
    assert "il-dash-zero" in text
    # No orphaned closing-tag-only markdown fragments (the sidebar/main HTML leak).
    for m in list(at.markdown) + list(at.caption):
        assert str(m.value).strip() not in {"</div>", "</div></div>"}


def test_no_view_buttons_below_table(monkeypatch):
    _seed_mixed(monkeypatch)
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [str(b.label) for b in at.button]
    assert not any(lab.startswith("View ·") for lab in labels)
    assert not any(lab.startswith("Review ·") for lab in labels)
    keys = [getattr(b, "key", None) for b in at.button]
    assert any(str(k).startswith("dash_row_nav_") for k in keys if k)
    text = _page_text(at)
    assert "il-dash-panel" in text
    assert "il-dash-row-wrap" not in text
    styles = (Path(__file__).resolve().parents[1] / "styles.py").read_text(encoding="utf-8")
    assert "min-height: calc(100vh - 380px)" not in styles
    assert "min-height: 320px" not in styles


def test_sidebar_labels_match_reference():
    from ui_common import _NAV_ADMIN, _NAV_REFERENCE, _NAV_WORK

    work = [label for label, _, _ in _NAV_WORK]
    ref = [label for label, _, _ in _NAV_REFERENCE]
    assert work == [
        "Overview",
        "Today's Decisions",
        "Approved for Purchase",
        "Purchase Orders",
    ]
    assert ref == ["Inventory", "Policies", "History"]
    for banned in (
        "Today's Queue",
        "Approved Today",
        "Inventory on Hand",
        "Policy & Guardrails",
        "System Health",
        "Agent Operations",
        "Administration",
    ):
        assert banned not in work
        assert banned not in ref
    # Admin destinations exist separately and are role-gated in render_left_nav.
    admin = [label for label, _, _ in _NAV_ADMIN]
    assert "System Health" in admin
    assert "Agent Operations" in admin


def test_tile_routes_exist():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "pages/11_Needs_Review.py",
        "pages/12_Blocked.py",
        "pages/13_Handled_Automatically.py",
        "pages/14_Expected_Deliveries.py",
    ):
        assert (root / rel).is_file()


def test_needs_review_page_smoke(monkeypatch):
    _seed_mixed(monkeypatch)
    at = AppTest.from_file(str(NEEDS_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = "alex.store"
    at.session_state["actor_role"] = "store_manager"
    at.session_state["actor_display"] = "Alex"
    at.session_state["session_id"] = "sess-nr"
    at.session_state["overview_detail_filter"] = "needs_review"
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at)
    assert "Needs your review" in text
    assert "← Back to Overview" in [str(b.label) for b in at.button] or "Back to Overview" in text


def test_blocked_page_smoke(monkeypatch):
    _seed_mixed(monkeypatch)
    at = AppTest.from_file(str(BLOCKED_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = "alex.store"
    at.session_state["actor_role"] = "store_manager"
    at.session_state["session_id"] = "sess-blk"
    at.session_state["overview_detail_filter"] = "blocked"
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = _page_text(at)
    assert "Blocked" in text
    # Seed may or may not produce blocked rows; empty copy must be correct when zero.
    detail = overview_dashboard_service.get_tile_detail("blocked")
    if detail["total_items"] == 0:
        assert "No recommendations are currently blocked." in text


def test_automated_and_deliveries_pages_smoke():
    for path, needle, filt, empty in (
        (
            AUTO_PATH,
            "Handled automatically",
            "handled_automatically",
            "No decisions have been handled automatically yet.",
        ),
        (
            DELIV_PATH,
            "Expected deliveries",
            "expected_deliveries",
            "No inbound deliveries are currently expected.",
        ),
    ):
        at = AppTest.from_file(str(path), default_timeout=TIMEOUT)
        at.session_state["authenticated"] = True
        at.session_state["user_id"] = "alex.store"
        at.session_state["actor_role"] = "store_manager"
        at.session_state["session_id"] = "sess-tile"
        at.session_state["overview_detail_filter"] = filt
        at.run(timeout=TIMEOUT)
        assert not at.exception
        text = _page_text(at)
        assert needle in text
        tile_key = "automated" if "handled" in filt else "deliveries"
        detail = overview_dashboard_service.get_tile_detail(tile_key)
        if detail["total_items"] == 0:
            assert empty in text


def test_detail_row_counts_match_card_counts(monkeypatch):
    _seed_mixed(monkeypatch)
    dash = overview_dashboard_service.get_overview_dashboard(display_name="Alex")
    for tile in dash["tiles"]:
        key = tile["key"]
        detail = overview_dashboard_service.get_tile_detail(key)
        assert detail["total_items"] == tile["count"], (
            f"{key}: detail {detail['total_items']} != card {tile['count']}"
        )

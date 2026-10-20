"""Overview zero-state read model + landing UI regression."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from services import morning_brief_service, overview_service
from services.overview_service import (
    DATA_NOT_READY,
    FAILED,
    FIRST_RUN_READY,
    MISSED_SCHEDULE,
    RUNNING,
    WAITING_FOR_SCHEDULE,
    build_zero_state,
)


APP_PATH = Path(__file__).parent / "ui_apps" / "overview_app.py"
TIMEOUT = 40


def _sources(*, ready: bool = True, unavailable: str | None = None) -> list[dict]:
    rows = []
    for key, label in (
        ("inventory", "Inventory"),
        ("sales", "Sales"),
        ("product", "Products"),
        ("supplier", "Suppliers"),
        ("erp", "Purchasing"),
    ):
        if unavailable and key == unavailable:
            status, kind = "Unavailable", "critical"
        elif ready:
            status, kind = "Ready", "success"
        else:
            status, kind = "Stale", "attention"
        rows.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "kind": kind,
                "display": status,
                "has_freshness": False,
            }
        )
    return rows


def test_first_run_ready_no_missed_warning():
    zs = build_zero_state(
        has_run=False,
        active_run=None,
        latest_terminal=None,
        schedule_enabled=True,
        scheduler_health={
            "status": "stale",
            "message": "No successful scheduled run within the expected schedule window.",
            "last_successful_run": None,
        },
        data_sources=_sources(ready=True),
        next_analysis_display="Today at 18:00 UTC",
        can_run=True,
        can_start_new_run=True,
    )
    assert zs is not None
    assert zs["key"] == FIRST_RUN_READY
    assert zs["show_warning"] is False


def test_waiting_for_schedule_unauthorized_no_cta():
    zs = build_zero_state(
        has_run=False,
        active_run=None,
        latest_terminal=None,
        schedule_enabled=True,
        scheduler_health={"status": "stale", "last_successful_run": None},
        data_sources=_sources(ready=True),
        next_analysis_display="Today at 18:00 UTC",
        can_run=False,
        can_start_new_run=True,
    )
    assert zs["key"] == WAITING_FOR_SCHEDULE
    assert zs["show_run_cta"] is False


def test_running_state_hides_run_cta():
    zs = build_zero_state(
        has_run=False,
        active_run={
            "status": "running",
            "scored_items": 2,
            "total_items": 10,
            "started_at": "2026-08-13T12:18:00+00:00",
        },
        latest_terminal=None,
        schedule_enabled=True,
        scheduler_health={"status": "healthy", "last_successful_run": {"run_id": "x"}},
        data_sources=_sources(ready=True),
        next_analysis_display="—",
        can_run=True,
        can_start_new_run=False,
    )
    assert zs["key"] == RUNNING
    assert zs["show_run_cta"] is False


def test_future_schedule_no_warning_when_never_ran():
    zs = build_zero_state(
        has_run=False,
        active_run=None,
        latest_terminal=None,
        schedule_enabled=True,
        scheduler_health={
            "status": "stale",
            "last_successful_run": None,
            "message": "No successful scheduled run within the expected schedule window.",
        },
        data_sources=_sources(ready=True),
        next_analysis_display="Tomorrow at 06:00 UTC",
        can_run=True,
        can_start_new_run=True,
    )
    assert zs["key"] == FIRST_RUN_READY
    assert zs["show_warning"] is False


def test_genuine_missed_schedule_warns():
    zs = build_zero_state(
        has_run=True,
        active_run=None,
        latest_terminal={"status": "completed", "run_id": "RUN-1"},
        schedule_enabled=True,
        scheduler_health={
            "status": "stale",
            "last_successful_run": {"run_id": "RUN-1"},
            "overdue_minutes": 120,
            "message": "No successful scheduled run within the expected schedule window.",
        },
        data_sources=_sources(ready=True),
        next_analysis_display="Today at 20:00 UTC",
        can_run=True,
        can_start_new_run=True,
    )
    assert zs["key"] == MISSED_SCHEDULE
    assert zs["show_warning"] is True


def test_failed_last_run_state():
    zs = build_zero_state(
        has_run=False,
        active_run=None,
        latest_terminal={"status": "failed", "run_id": "RUN-FAIL"},
        schedule_enabled=True,
        scheduler_health={"status": "failed", "last_successful_run": None},
        data_sources=_sources(ready=True),
        next_analysis_display="Today at 18:00 UTC",
        can_run=True,
        can_start_new_run=True,
    )
    assert zs["key"] == FAILED
    assert zs["show_run_cta"] is True


def test_data_not_ready_blocks_run_cta():
    zs = build_zero_state(
        has_run=False,
        active_run=None,
        latest_terminal=None,
        schedule_enabled=True,
        scheduler_health={"status": "stale", "last_successful_run": None},
        data_sources=_sources(ready=True, unavailable="inventory"),
        next_analysis_display="Today at 18:00 UTC",
        can_run=True,
        can_start_new_run=True,
        blocking_feeds=[{"message": "Inventory feed unavailable"}],
    )
    assert zs["key"] == DATA_NOT_READY
    assert zs["show_run_cta"] is False


def test_overview_service_first_run_payload():
    payload = overview_service.get_replenishment_overview(actor_role="administrator")
    assert payload["has_run"] is False
    landing = morning_brief_service.build_landing_workspace(
        payload, display_name="Dana Administrator"
    )
    assert landing["mode"] == "healthy"
    assert "scheduled analysis" not in landing["greeting"].lower()


def test_overview_service_viewer_waiting():
    payload = overview_service.get_replenishment_overview(actor_role="viewer")
    assert payload["can_run_now"] is False


def _app(role: str = "store_manager", user_id: str = "alex.store", display: str = "Alex") -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["authenticated"] = True
    at.session_state["user_id"] = user_id
    at.session_state["actor_role"] = role
    at.session_state["actor_display"] = display
    at.session_state["session_id"] = "sess-overview-zero"
    return at


def test_ui_first_run_admin_no_ops_controls():
    at = _app(role="administrator", user_id="admin.demo", display="Dana Administrator")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Needs your review" in text
    assert "Expected deliveries" in text
    labels = [b.label for b in at.button]
    assert "Run Analysis Now" not in labels
    assert "Review inventory now" not in labels


def test_ui_viewer_no_run_analysis_button():
    at = _app(role="viewer", user_id="riley.viewer", display="Riley Viewer")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Run Analysis Now" not in labels
    assert "Review inventory now" not in labels


def test_landing_does_not_call_run_now_on_load(monkeypatch):
    run_now = MagicMock()
    monkeypatch.setattr("services.scheduler_service.run_now", run_now)
    at = _app(role="administrator", user_id="admin.demo", display="Dana Administrator")
    at.run(timeout=TIMEOUT)
    run_now.assert_not_called()


def test_ui_running_state_healthy_or_actionable(monkeypatch):
    monkeypatch.setattr(
        "services.scheduler_service.get_run_trigger_status",
        lambda: {
            "active_run": {
                "run_id": "RUN-ACTIVE",
                "status": "running",
                "scored_items": 3,
                "total_items": 12,
                "started_at": "2026-08-13T17:00:00+00:00",
            },
            "latest_run": None,
            "last_run": None,
            "current_status": "running",
            "next_run_display": "—",
            "last_run_display": "—",
            "can_start_new_run": False,
            "schedule": {"enabled": True},
            "scheduler_health": {
                "status": "healthy",
                "last_successful_run": {"run_id": "OLD"},
                "message": "ok",
            },
        },
    )
    payload = overview_service.get_replenishment_overview(actor_role="administrator")
    assert payload["zero_state"]["key"] == RUNNING
    at = _app(role="administrator", user_id="admin.demo", display="Dana Administrator")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Run Analysis Now" not in labels

"""Checkpoint 7 — automated replenishment runs (schedule + Run now)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from database.connection import get_session
from repositories import run_repository
from services import (
    auth_service,
    policy_service,
    scheduler_service,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_replenishment_batch.py"
MODULE = ["-m", "jobs.run_replenishment"]


def test_run_creation_persists_manual_run():
    policy_service.ensure_default_policy()
    outcome = scheduler_service.run_now(
        actor="admin.demo",
        actor_role="administrator",
        session_id="sess-admin-run",
    )
    assert outcome["started"] is True
    run = outcome["run"]
    assert run["run_id"]
    assert run["status"] in {"completed", "completed_with_errors"}
    assert run["trigger_type"] == "manual"
    assert run["total_items"] >= 1
    assert run["scored_items"] + run["failed_items"] == run["total_items"]

    with get_session() as session:
        saved = run_repository.get_run(session, run["run_id"])
    assert saved is not None
    assert saved.trigger_type == "manual"
    assert saved.status == run["status"]


def test_manual_trigger_scores_full_catalog():
    policy_service.ensure_default_policy()
    status_before = scheduler_service.get_run_trigger_status()
    assert status_before["eligible_pair_count"] >= 10
    assert status_before["can_start_new_run"] is True
    assert status_before["schedule"]["interval_hours"] == 6

    outcome = scheduler_service.run_now(
        actor="admin.demo",
        actor_role="administrator",
        session_id="sess-admin-run",
    )
    assert outcome["started"] is True
    run = outcome["run"]
    assert run["total_items"] == status_before["eligible_pair_count"]

    status_after = scheduler_service.get_run_trigger_status()
    assert status_after["latest_run"]["run_id"] == run["run_id"]
    assert status_after["active_run"] is None
    assert status_after["skus_scored"] == run["scored_items"]
    assert status_after["current_status"] == run["status"]
    assert status_after["next_run_at"]
    assert status_after["last_run_display"] != "—"


def test_scheduled_trigger_via_service():
    policy_service.ensure_default_policy()
    outcome = scheduler_service.run_scheduled(
        initiated_by="unit-cron",
        store_sku_pairs=[("ST001", "SKU-1001"), ("ST001", "SKU-1002")],
    )
    assert outcome["started"] is True
    assert outcome["run"]["trigger_type"] == "scheduled"
    assert outcome["run"]["initiated_by"] == "unit-cron"
    assert outcome["run"]["total_items"] == 2


def test_cron_secret_required_when_configured(monkeypatch):
    monkeypatch.setattr("services.scheduler_service.CRON_SECRET", "top-secret")

    with pytest.raises(auth_service.AuthError):
        scheduler_service.run_scheduled(initiated_by="cron", cron_secret=None)

    with pytest.raises(auth_service.AuthError):
        scheduler_service.run_scheduled(initiated_by="cron", cron_secret="wrong")

    outcome = scheduler_service.run_scheduled(
        initiated_by="cron",
        cron_secret="top-secret",
        store_sku_pairs=[("ST001", "SKU-1002")],
    )
    assert outcome["started"] is True


def test_non_admin_cannot_run_now():
    with pytest.raises(auth_service.AuthError):
        scheduler_service.run_now(
            actor="alex.store",
            actor_role="store_manager",
        )


def test_blocks_overlapping_run(monkeypatch):
    policy_service.ensure_default_policy()

    class _FakeActive:
        run_id = "RUN-ACTIVE"
        status = "running"
        trigger_type = "manual"
        initiated_by = "admin.demo"
        started_at = None
        completed_at = None
        created_at = None
        total_items = 10
        scored_items = 1
        auto_released_items = 0
        review_items = 0
        blocked_items = 0
        failed_items = 0
        policy_version = "v1"
        error_summary = None

    monkeypatch.setattr(
        "repositories.run_repository.get_active_run",
        lambda session: _FakeActive(),
    )
    outcome = scheduler_service.run_now(
        actor="admin.demo",
        actor_role="administrator",
    )
    assert outcome["started"] is False
    assert outcome["blocked_reason"] == "active_run"
    assert outcome["active_run"]["run_id"] == "RUN-ACTIVE"


def test_compute_next_run_from_cron(monkeypatch):
    monkeypatch.setattr(
        "services.schedule_time.REPLENISHMENT_CRON", "0 */6 * * *"
    )
    monkeypatch.setattr(
        "services.schedule_time.REPLENISHMENT_TIMEZONE", "UTC"
    )
    nxt = scheduler_service.compute_next_run_at(
        last_completed_at=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        interval_hours=6,
        now=datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc),
    )
    # Cron-aligned: next fire after 14:00 UTC is 18:00 — not last+6h.
    assert nxt == datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc)

    overdue = scheduler_service.compute_next_run_at(
        last_completed_at=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        interval_hours=6,
        now=datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc),
    )
    assert overdue == datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)


def test_status_only_does_not_create_run():
    policy_service.ensure_default_policy()
    before = scheduler_service.get_run_trigger_status()
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, *MODULE, "--status-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "latest_run" in payload
    assert "next_run_at" in payload
    assert payload["schedule"]["interval_hours"] == 6
    after = scheduler_service.get_run_trigger_status()
    assert (after.get("latest_run") or {}).get("run_id") == (
        (before.get("latest_run") or {}).get("run_id")
    )


def test_cli_module_scheduled_subset():
    policy_service.ensure_default_policy()
    env = os.environ.copy()
    proc = subprocess.run(
        [
            sys.executable,
            *MODULE,
            "--trigger",
            "scheduled",
            "--initiated-by",
            "cli-test",
            "--pair",
            "ST001:SKU-1005",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    outcome = json.loads(proc.stdout)
    assert outcome["started"] is True
    assert outcome["run"]["total_items"] == 1
    assert outcome["run"]["trigger_type"] == "scheduled"


def test_legacy_script_wrapper_still_works():
    policy_service.ensure_default_policy()
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--status-only"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "schedule" in payload


def test_schedule_config_and_health():
    from health import check_health

    cfg = scheduler_service.get_schedule_config()
    assert cfg["interval_hours"] == 6
    assert "cron" in cfg
    assert cfg["entry_point"] == "python -m jobs.run_replenishment"

    payload = check_health()
    assert payload["batch_schedule"]["interval_hours"] == 6
    assert payload["batch_schedule"]["entry_point"] == "python -m jobs.run_replenishment"


def test_topbar_metrics_are_live_not_hardcoded():
    policy_service.ensure_default_policy()
    idle = scheduler_service.get_topbar_run_metrics()
    assert idle["current_status"] in {"idle", "completed", "completed_with_errors", "failed"}
    assert idle["status_pill"] == "Monitoring inventory · First analysis in progress"
    for banned in ("Idle", "Waiting", "Next Run", "Scheduler", "Current Status"):
        assert banned.lower() not in idle["status_pill"].lower()

    outcome = scheduler_service.run_scheduled(
        initiated_by="topbar-test",
        store_sku_pairs=[("ST001", "SKU-1001")],
    )
    metrics = scheduler_service.get_topbar_run_metrics()
    assert metrics["skus_scored"] == outcome["run"]["scored_items"]
    assert metrics["last_agent_run"] != "—"
    assert "2026" in metrics["last_agent_run"] or "UTC" in metrics["last_agent_run"]
    assert metrics["next_run"] != "—"
    assert metrics["current_status"] == outcome["run"]["status"]
    pill = metrics["status_pill"]
    assert pill.startswith("Last agent run ")
    assert "SKUs scored" in pill
    assert " CT · " in pill
    assert str(outcome["run"]["scored_items"]) in pill
    for banned in ("Idle", "Waiting", "Next Run", "Scheduler", "Current Status"):
        assert banned.lower() not in pill.lower()


def test_topbar_status_pill_formats_completed_run():
    text = scheduler_service.format_topbar_status_pill(
        {
            "latest_run": {
                "completed_at": "2026-08-14T11:00:00+00:00",
                "started_at": "2026-08-14T11:00:00+00:00",
                "scored_items": 412,
            },
            "skus_scored": 412,
        }
    )
    assert text == (
        "Last agent run 06:00 CT · 412 SKUs scored · Friday, August 14 · 06:00 CT"
    )
    assert (
        scheduler_service.format_topbar_status_pill({"latest_run": None})
        == "Monitoring inventory · First analysis in progress"
    )

def test_retry_failed_run_starts_new_run(monkeypatch):
    policy_service.ensure_default_policy()
    first = scheduler_service.run_scheduled(
        initiated_by="seed",
        store_sku_pairs=[("ST001", "SKU-1001")],
    )
    run_id = first["run"]["run_id"]

    with get_session() as session:
        run = run_repository.get_run(session, run_id)
        assert run is not None
        run_repository.save_run(
            session,
            run.model_copy(update={"status": "failed", "failed_items": 1}),
        )

    outcome = scheduler_service.retry_failed_run(
        actor="admin.demo",
        actor_role="administrator",
        run_id=run_id,
        session_id="sess-retry",
    )
    assert outcome["started"] is True
    assert outcome["run"]["trigger_type"] == "retry"
    assert outcome["run"]["run_id"] != run_id


def test_admin_ui_run_now_button():
    from streamlit.testing.v1 import AppTest

    policy_service.ensure_default_policy()
    app_path = Path(__file__).parent / "ui_apps" / "administration_app.py"
    at = AppTest.from_file(str(app_path), default_timeout=60)
    at.run(timeout=60)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "Run now" in labels
    run_btn = next(b for b in at.button if b.label == "Run now")
    run_btn.click().run(timeout=120)
    assert not at.exception
    assert "admin_run_outcome" in at.session_state
    assert at.session_state["admin_run_outcome"]["started"] is True

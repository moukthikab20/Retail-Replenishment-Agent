"""Scheduled replenishment gap closure — enable/disable, buckets, lock, health."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from database.connection import get_session
from repositories import audit_repository, run_repository
from services import policy_service, queue_service, scheduler_service
from services.schedule_time import (
    current_schedule_bucket,
    invocation_key_for_bucket,
    next_scheduled_occurrence,
)
from services.scheduler_lock import force_clear_batch_lock, try_acquire_batch_lock

ROOT = Path(__file__).resolve().parents[1]
MODULE = ["-m", "jobs.run_replenishment"]


@pytest.fixture(autouse=True)
def _clear_lock():
    force_clear_batch_lock()
    yield
    force_clear_batch_lock()


def test_schedule_enabled_config(monkeypatch):
    monkeypatch.setattr("services.scheduler_service.REPLENISHMENT_SCHEDULE_ENABLED", True)
    cfg = scheduler_service.get_schedule_config()
    assert cfg["enabled"] is True
    assert cfg["cron"]
    assert cfg["timezone"]


def test_schedule_disabled_skips_scheduled_but_allows_manual(monkeypatch):
    policy_service.ensure_default_policy()
    monkeypatch.setattr("services.scheduler_service.REPLENISHMENT_SCHEDULE_ENABLED", False)

    skipped = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001")],
    )
    assert skipped["started"] is False
    assert skipped["blocked_reason"] == "schedule_disabled"
    assert skipped.get("harmless_skip") is True

    with get_session() as session:
        events = audit_repository.list_audit_events(session, limit=50)
    types = {e.event_type for e in events}
    assert "scheduled_replenishment_skipped_disabled" in types

    manual = scheduler_service.run_now(
        actor="admin.demo",
        actor_role="administrator",
        store_sku_pairs=[("ST001", "SKU-1001")],
    )
    assert manual["started"] is True
    assert manual["run"]["trigger_type"] == "manual"

    status = scheduler_service.get_run_trigger_status()
    assert status["next_run_display"] == "Not scheduled"
    health = scheduler_service.get_scheduler_health()
    assert health["status"] == "disabled"


def test_scheduled_invocation_key_and_duplicate_bucket(monkeypatch):
    policy_service.ensure_default_policy()
    monkeypatch.setattr("services.scheduler_service.REPLENISHMENT_SCHEDULE_ENABLED", True)
    bucket = datetime(2026, 8, 12, 6, 0, tzinfo=ZoneInfo("America/Chicago"))
    key = invocation_key_for_bucket(bucket)

    first = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001"), ("ST001", "SKU-1002")],
        scheduled_for=bucket,
        invocation_key=key,
    )
    assert first["started"] is True
    assert first["run"]["trigger_type"] == "scheduled"
    assert first["run"]["invocation_key"] == key
    run_id = first["run"]["run_id"]

    with get_session() as session:
        recs1 = run_repository.list_recommendations_for_run(session, run_id)
    n_recs = len(recs1)

    second = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001"), ("ST001", "SKU-1002")],
        scheduled_for=bucket,
        invocation_key=key,
    )
    assert second["started"] is False
    assert second["blocked_reason"] == "duplicate_invocation"
    assert second["run"]["run_id"] == run_id

    with get_session() as session:
        recs2 = run_repository.list_recommendations_for_run(session, run_id)
        events = audit_repository.list_audit_events(session, limit=100)
    assert len(recs2) == n_recs
    assert any(e.event_type == "scheduled_replenishment_skipped_duplicate" for e in events)

    # Next bucket → new run
    next_bucket = bucket + timedelta(hours=6)
    third = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001")],
        scheduled_for=next_bucket,
    )
    assert third["started"] is True
    assert third["run"]["run_id"] != run_id


def test_overlap_lock_and_audit(monkeypatch):
    policy_service.ensure_default_policy()
    held = try_acquire_batch_lock(holder="test-holder")
    assert held["acquired"] is True

    outcome = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001")],
        scheduled_for=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
    )
    assert outcome["started"] is False
    assert outcome["blocked_reason"] == "active_run"

    with get_session() as session:
        events = audit_repository.list_audit_events(session, limit=50)
    assert any(e.event_type == "scheduled_replenishment_skipped_overlap" for e in events)


def test_concurrent_triggers_single_winner():
    policy_service.ensure_default_policy()
    bucket = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    results: list[dict] = []
    errors: list[BaseException] = []

    def _worker():
        try:
            results.append(
                scheduler_service.run_scheduled(
                    initiated_by="replenishment_scheduler",
                    store_sku_pairs=[("ST001", "SKU-1001")],
                    scheduled_for=bucket,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, f"worker errors: {errors}"
    started = [r for r in results if r.get("started")]
    skipped = [r for r in results if not r.get("started")]
    assert len(results) == 2
    assert len(started) == 1
    assert len(skipped) == 1
    assert skipped[0]["blocked_reason"] in {
        "active_run",
        "duplicate_invocation",
    }


def test_cron_derived_next_run_and_timezone(monkeypatch):
    monkeypatch.setattr("services.schedule_time.REPLENISHMENT_CRON", "0 */6 * * *")
    monkeypatch.setattr("services.schedule_time.REPLENISHMENT_TIMEZONE", "America/Chicago")
    now = datetime(2026, 8, 12, 14, 30, tzinfo=timezone.utc)
    nxt = next_scheduled_occurrence(now=now)
    assert nxt.tzinfo is not None
    # 14:30 UTC = 09:30 America/Chicago → next 12:00 Chicago
    chicago = nxt.astimezone(ZoneInfo("America/Chicago"))
    assert chicago.hour == 12
    assert chicago.minute == 0

    bucket = current_schedule_bucket(now=now)
    key = invocation_key_for_bucket(bucket)
    assert key.startswith("scheduled:")
    assert "T" in key


def test_scheduler_health_states(monkeypatch):
    policy_service.ensure_default_policy()
    monkeypatch.setattr("services.scheduler_service.REPLENISHMENT_SCHEDULE_ENABLED", False)
    assert scheduler_service.get_scheduler_health()["status"] == "disabled"

    monkeypatch.setattr("services.scheduler_service.REPLENISHMENT_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(
        "services.scheduler_service.REPLENISHMENT_STALE_TOLERANCE_MINUTES", 30
    )
    # No successful scheduled run yet → stale
    stale = scheduler_service.get_scheduler_health(
        now=datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)
    )
    assert stale["status"] == "stale"

    bucket = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)
    ok = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001")],
        scheduled_for=bucket,
        now=bucket + timedelta(minutes=1),
    )
    assert ok["started"] is True
    healthy = scheduler_service.get_scheduler_health(
        now=bucket + timedelta(hours=1)
    )
    assert healthy["status"] == "healthy"

    # Mark scheduled run failed → failed health
    with get_session() as session:
        run = run_repository.get_run(session, ok["run"]["run_id"])
        assert run is not None
        run_repository.save_run(
            session, run.model_copy(update={"status": "failed", "failed_items": 1})
        )
    failed = scheduler_service.get_scheduler_health(
        now=bucket + timedelta(hours=1)
    )
    assert failed["status"] == "failed"

    # New successful scheduled run restores health
    restore = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1002")],
        scheduled_for=bucket + timedelta(hours=6),
    )
    assert restore["started"] is True
    restored = scheduler_service.get_scheduler_health(
        now=bucket + timedelta(hours=7)
    )
    assert restored["status"] == "healthy"


def test_cli_exit_codes_for_skip_and_failure(monkeypatch):
    policy_service.ensure_default_policy()
    env = os.environ.copy()
    env["REPLENISHMENT_SCHEDULE_ENABLED"] = "false"
    proc = subprocess.run(
        [sys.executable, *MODULE, "--trigger", "scheduled", "--pair", "ST001:SKU-1001"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["blocked_reason"] == "schedule_disabled"


def test_openai_disabled_scheduled_run(monkeypatch):
    policy_service.ensure_default_policy()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("config.OPENAI_API_KEY", "")
    outcome = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001"), ("ST002", "SKU-1001")],
        scheduled_for=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc),
    )
    assert outcome["started"] is True
    assert outcome["run"]["status"] in {"completed", "completed_with_errors"}
    assert outcome["run"]["scored_items"] + outcome["run"]["failed_items"] == 2


def test_integration_scheduled_bucket_dispositions_and_no_duplicates():
    policy_service.ensure_default_policy()
    bucket = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)
    first = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[
            ("ST001", "SKU-1001"),
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1003"),
            ("ST001", "SKU-1004"),
        ],
        scheduled_for=bucket,
    )
    assert first["started"] is True
    run_id = first["run"]["run_id"]
    assert first["run"]["status"] in {"completed", "completed_with_errors"}

    with get_session() as session:
        items = run_repository.list_run_items(session, run_id)
        recs = run_repository.list_recommendations_for_run(session, run_id)
        events = audit_repository.list_audit_events(session, limit=200)
    assert len(items) == 4
    assert len(recs) >= 1
    dispositions = {i.disposition for i in items if i.disposition}
    assert dispositions  # at least some dispositions persisted
    event_types = {e.event_type for e in events}
    assert "scheduled_replenishment_triggered" in event_types
    assert "scheduled_replenishment_completed" in event_types or (
        first["run"]["status"] == "failed"
    )

    queue = queue_service.get_todays_queue(run_id=run_id)
    assert queue["run"]["run_id"] == run_id

    # Same bucket again — no duplicate recs / intents
    again = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[
            ("ST001", "SKU-1001"),
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1003"),
            ("ST001", "SKU-1004"),
        ],
        scheduled_for=bucket,
    )
    assert again["started"] is False
    assert again["blocked_reason"] == "duplicate_invocation"
    with get_session() as session:
        recs2 = run_repository.list_recommendations_for_run(session, run_id)
    assert len(recs2) == len(recs)

    # Next bucket creates a new run
    nxt = scheduler_service.run_scheduled(
        initiated_by="replenishment_scheduler",
        store_sku_pairs=[("ST001", "SKU-1001")],
        scheduled_for=bucket + timedelta(hours=6),
    )
    assert nxt["started"] is True
    assert nxt["run"]["run_id"] != run_id


def test_direct_batch_still_callable_for_tests():
    """Low-level API remains usable; production entry is trigger_replenishment_run."""
    from services import batch_run_service

    policy_service.ensure_default_policy()
    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1001")],
        trigger_type="manual",
        initiated_by="test-direct",
    )
    assert result["run_id"]
    assert result["trigger_type"] == "manual"

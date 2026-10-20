"""Checkpoint 4 — Approve / Adjust / Decline + Approved Today."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services import (
    batch_run_service,
    disposition_service,
    policy_service,
    queue_service,
    recommendation_service,
)


APPROVED_APP = Path(__file__).parent / "ui_apps" / "approved_today_app.py"
QUEUE_APP = Path(__file__).parent / "ui_apps" / "todays_queue_app.py"
TIMEOUT = 30


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
            ("ST001", "SKU-1001"),  # human_review
            ("ST001", "SKU-1002"),  # auto_release
            ("ST001", "SKU-1004"),  # blocked
            ("ST001", "SKU-1005"),
        ],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-disp",
    )


def _human_review_id(run: dict) -> str:
    for item in run["items"]:
        if item.get("disposition") == "human_review" and item.get("recommendation_id"):
            return item["recommendation_id"]
    raise AssertionError("No human_review item in run")


def test_approve_as_recommended_moves_to_approved_today(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _human_review_id(run)

    before_queue = queue_service.get_todays_queue(filter_key="needs_review")
    assert any(r["recommendation_id"] == rec_id for r in before_queue["rows"])

    result = disposition_service.approve_recommendation(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="sess-disp",
    )
    assert result["outcome"] == "approved"
    assert result["final_quantity"] is not None

    after_queue = queue_service.get_todays_queue(filter_key="needs_review")
    assert all(r["recommendation_id"] != rec_id for r in after_queue["rows"])

    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert approved["summary"]["human_approved"] >= 1
    assert approved["summary"]["auto_released"] >= 1
    human_rows = [r for r in approved["rows"] if r["recommendation_id"] == rec_id]
    assert len(human_rows) == 1
    assert human_rows[0]["source"] == "Human approved"
    assert human_rows[0]["decided_by"] == "alex.store"
    assert human_rows[0]["final_quantity"] == result["final_quantity"]

    # Three-quantity separation preserved on recommendation
    rec = recommendation_service.get_recommendation(rec_id)
    assert rec["agent_recommended_quantity"] == result["final_quantity"]
    assert rec["status"] == "approved"


def test_adjust_requires_reason_and_preserves_agent_qty(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _human_review_id(run)
    rec = recommendation_service.get_recommendation(rec_id)
    agent_qty = rec["agent_recommended_quantity"]
    case_pack = rec["case_pack"]
    new_qty = agent_qty + case_pack

    with pytest.raises(ValueError, match="Comments are required|Override reason|reason"):
        disposition_service.approve_recommendation(
            recommendation_id=rec_id,
            actor="jamie.planner",
            actor_role="inventory_planner",
            human_proposed_quantity=new_qty,
            override_reason="",
        )

    result = disposition_service.approve_recommendation(
        recommendation_id=rec_id,
        actor="jamie.planner",
        actor_role="inventory_planner",
        human_proposed_quantity=new_qty,
        override_reason="Increase cover for promo week",
        user_id="jamie.planner",
        session_id="sess-disp",
    )
    assert result["outcome"] in {"approved", "pending_approval"}
    assert result["final_quantity"] == new_qty

    refreshed = recommendation_service.get_recommendation(rec_id)
    assert refreshed["agent_recommended_quantity"] == agent_qty


def test_decline_removes_from_needs_review_not_approved_today(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _human_review_id(run)

    result = disposition_service.decline_recommendation(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
        reason="Not needed this cycle",
    )
    assert result["outcome"] == "declined"

    needs = queue_service.get_todays_queue(filter_key="needs_review")
    assert all(r["recommendation_id"] != rec_id for r in needs["rows"])

    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert all(r["recommendation_id"] != rec_id for r in approved["rows"])


def test_cannot_approve_blocked(monkeypatch):
    run = _seed_mixed(monkeypatch)
    blocked_id = None
    for item in run["items"]:
        if item.get("disposition") == "blocked" and item.get("recommendation_id"):
            blocked_id = item["recommendation_id"]
            break
    assert blocked_id
    with pytest.raises(ValueError, match="Blocked|human_review disposition"):
        disposition_service.approve_recommendation(
            recommendation_id=blocked_id,
            actor="alex.store",
            actor_role="store_manager",
        )


def test_approve_all_within_policy(monkeypatch):
    run = _seed_mixed(monkeypatch)
    before = queue_service.get_todays_queue(filter_key="needs_review")
    assert before["summary"]["needs_review"] >= 1

    bulk = disposition_service.approve_all_within_policy(
        actor="alex.store",
        actor_role="store_manager",
        run_id=run["run_id"],
        user_id="alex.store",
        session_id="sess-disp",
    )
    assert bulk["attempted"] >= 1
    assert bulk["approved"] + bulk["pending_approval"] + bulk["skipped"] + bulk["failed"] == bulk[
        "attempted"
    ]
    assert bulk["approved"] >= 1

    after = queue_service.get_todays_queue(filter_key="needs_review")
    assert after["summary"]["needs_review"] < before["summary"]["needs_review"]

    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert approved["summary"]["human_approved"] >= bulk["approved"]


def test_duplicate_approve_is_idempotent(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _human_review_id(run)
    first = disposition_service.approve_recommendation(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert first["outcome"] == "approved"
    second = disposition_service.approve_recommendation(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert second["outcome"] == "already_approved"


def test_viewer_cannot_approve(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _human_review_id(run)
    with pytest.raises(Exception):
        disposition_service.approve_recommendation(
            recommendation_id=rec_id,
            actor="riley.viewer",
            actor_role="viewer",
        )


def test_approved_today_includes_auto_release_without_human(monkeypatch):
    run = _seed_mixed(monkeypatch)
    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert approved["summary"]["auto_released"] >= 1
    assert approved["summary"]["human_approved"] == 0
    assert all(r["source"] == "Auto-released" for r in approved["rows"])
    assert all(r["decided_by"] == "policy" for r in approved["rows"])


def test_approved_today_ui_lists_auto_released(monkeypatch):
    _seed_mixed(monkeypatch)
    at = AppTest.from_file(str(APPROVED_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Approved for Purchase" in text or "Approved" in text
    assert "Approved today" in text or "Handled automatically" in text
    assert "Handled automatically" in text or "Auto-released" in text
    lowered = text.lower()
    assert "placeholder" not in lowered
    assert "later checkpoint" not in lowered


def test_queue_ui_shows_bulk_approve(monkeypatch):
    _seed_mixed(monkeypatch)
    at = AppTest.from_file(str(QUEUE_APP), default_timeout=TIMEOUT)
    at.run(timeout=TIMEOUT)
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any(label == "Approve within policy" for label in labels)
    assert not any(label.startswith("Review ·") for label in labels)
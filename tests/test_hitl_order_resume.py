"""Checkpoint 6 — HITL pause/serialize/reload/resume integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.hitl import build_pause_envelope, parse_state_envelope, validate_resume_guards
from agent.runner import (
    get_pending_order_flow,
    resume_order_run,
    start_order_agent_after_approval,
)
from database.connection import get_session
from repositories import approval_repository, audit_repository, purchase_order_repository
from services import (
    approval_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)
from services.errors import AppError


def _approved_flow(*, human_qty: int | None = None):
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="hitl test",
        user_id="jamie.planner",
        session_id="sess-hitl",
    )
    agent_qty = rec.agent_recommended_quantity
    qty = human_qty if human_qty is not None else agent_qty
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="manual" if qty != agent_qty else "use_agent",
        human_proposed_quantity=qty if qty != agent_qty else None,
        override_reason="HITL test override" if qty != agent_qty else None,
        submitted_by="jamie.planner",
        actor_role="inventory_planner",
        user_id="jamie.planner",
        session_id="sess-hitl",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor="jamie.planner",
        actor_role="inventory_planner",
    )
    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="casey.category",
        actor_role="category_manager",
    )
    return rec, review, decided


def test_pause_serialize_reload_and_version(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow()

    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
        user_id="casey.category",
        session_id="sess-hitl",
    )
    assert paused["status"] == "paused"
    assert paused["pending_tool"] == "create_mock_purchase_order"
    assert paused["pending_args"]["approval_id"] == approval.approval_id
    assert paused.get("state_version") == 1

    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, paused["run_id"])
        assert row is not None
        assert row.status in {"paused", "waiting_for_human"}
        envelope = parse_state_envelope(row.state_json)
        assert envelope.get("version") == 1 or envelope.get("schema_version")
        assert envelope.get("mode") == "deterministic_hitl" or envelope.get("guards")
        guards = envelope.get("guards") or {}
        assert guards.get("approval_id") == approval.approval_id
        assert "api_key" not in json.dumps(envelope)

    reloaded = get_pending_order_flow(approval.approval_id)
    assert reloaded is not None
    assert reloaded["status"] == "paused"
    assert reloaded["run_id"] == paused["run_id"]


def test_approve_resume_creates_order_successfully(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    resumed = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="admin.demo",
        actor_role="administrator",
    )
    assert resumed["status"] == "completed"
    po = resumed["purchase_order"]
    assert po["approval_id"] == approval.approval_id
    assert po["agent_recommended_quantity"] == approval.agent_recommended_quantity
    assert po["human_proposed_quantity"] == approval.human_proposed_quantity
    assert po["approved_final_quantity"] == approval.approved_final_quantity


def test_reject_sensitive_tool_does_not_create_order(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    rejected = resume_order_run(
        run_id=paused["run_id"],
        approve=False,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert rejected["status"] == "rejected"
    with get_session() as session:
        assert (
            purchase_order_repository.get_purchase_order_by_approval(
                session, approval.approval_id
            )
            is None
        )


def test_duplicate_resume_does_not_create_second_order(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    first = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="casey.category",
        actor_role="category_manager",
    )
    second = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="admin.demo",
        actor_role="administrator",
    )
    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert (
        first["purchase_order"]["purchase_order_id"]
        == second["purchase_order"]["purchase_order_id"]
    )


def test_expired_approval_pause_blocks_resume(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, paused["run_id"])
        envelope = parse_state_envelope(row.state_json)
        past = datetime.now(timezone.utc) - timedelta(hours=3)
        envelope["guards"]["paused_at"] = past.isoformat()
        envelope["guards"]["expires_at"] = (past + timedelta(minutes=1)).isoformat()
        row.state_json = json.dumps(envelope)
        session.flush()

    result = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "hitl_expired"
    with get_session() as session:
        assert (
            purchase_order_repository.get_purchase_order_by_approval(
                session, approval.approval_id
            )
            is None
        )


def test_changed_approved_quantity_blocks_resume(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow(human_qty=None)
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    # Mutate approved quantity after pause (simulates changed approval record).
    with get_session() as session:
        current = approval_repository.get_approval(session, approval.approval_id)
        assert current is not None
        current.approved_final_quantity = int(current.approved_final_quantity or 0) + 12
        approval_repository.save_approval(session, current)

    result = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "hitl_quantity_changed"


def test_revoked_formal_approval_blocks_resume(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, _review, approval = _approved_flow()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    with get_session() as session:
        current = approval_repository.get_approval(session, approval.approval_id)
        assert current is not None
        current.status = "rejected"
        current.approved_final_quantity = None
        approval_repository.save_approval(session, current)

    result = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert result["status"] == "error"
    assert result["error_code"] == "hitl_approval_not_approved"


def test_sdk_interruption_pause_and_resume_path(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec, _review, approval = _approved_flow()

    interruption = SimpleNamespace(
        tool_name="create_mock_purchase_order",
        arguments={"approval_id": approval.approval_id},
    )
    fake_state = MagicMock()
    fake_state.to_json.return_value = {
        "current_turn": 1,
        "interruptions": ["create_mock_purchase_order"],
        "context": {"run_id": "x", "api_key": "should-not-leak"},
    }
    fake_state.get_interruptions.return_value = [interruption]
    fake_state.approve = MagicMock()

    start_result = SimpleNamespace(
        interruptions=[interruption],
        to_state=lambda: fake_state,
        final_output=None,
    )

    po_holder: dict = {}

    def _fake_execute(agent, payload, **kwargs):
        # First call is start (string prompt); second is resume (state).
        if isinstance(payload, str):
            return start_result
        # On resume, create the PO via service (simulating tool completion).
        po = purchase_order_service.create_mock_purchase_order(
            approval.approval_id,
            actor="casey.category",
            actor_role="category_manager",
        )
        po_holder["po"] = po
        return SimpleNamespace(
            interruptions=[],
            final_output={"purchase_order_id": po.purchase_order_id},
            to_state=lambda: fake_state,
        )

    monkeypatch.setattr("agent.runner._execute_runner", _fake_execute)
    monkeypatch.setattr("agent.runner.build_replenishment_agent", MagicMock())
    monkeypatch.setattr(
        "agent.runner._load_run_state",
        lambda agent, payload: fake_state,
    )

    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert paused["status"] == "paused"
    assert paused["mode"] == "sdk"
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, paused["run_id"])
        envelope = parse_state_envelope(row.state_json)
        assert envelope["mode"] == "sdk"
        assert envelope["sdk_run_state"] is not None
        # Secrets redacted in persisted envelope
        assert "[redacted]" in json.dumps(envelope) or "should-not-leak" not in json.dumps(
            envelope
        )

    resumed = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert resumed["status"] == "completed"
    assert resumed["purchase_order"]["purchase_order_id"] == po_holder["po"].purchase_order_id
    fake_state.approve.assert_called()


def test_validate_resume_guards_helper():
    envelope = build_pause_envelope(
        approval_id="APR-missing",
        recommendation_id="REC-x",
        approved_final_quantity=12,
        pending_tool_name="create_mock_purchase_order",
        pending_tool_args={"approval_id": "APR-missing"},
        sdk_run_state=None,
        mode="deterministic_hitl",
    )
    with pytest.raises(AppError) as exc:
        validate_resume_guards(envelope, row_status="paused")
    assert exc.value.code == "hitl_approval_not_approved"

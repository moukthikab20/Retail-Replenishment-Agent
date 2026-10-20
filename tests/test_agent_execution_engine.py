"""Durable agent execution engine — state machine, tools, HITL, concurrency."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from agent.execution_engine import (
    complete_execution,
    create_execution,
    fail_execution,
    get_execution,
    mark_waiting_for_human,
    record_tool_finish,
    record_tool_start,
    resume_agent_execution,
    schedule_retry,
    start_execution,
    transition_execution,
    try_complete_execution,
)
from agent.execution_failures import FailureClass, classify_failure
from agent.execution_states import (
    ExecutionStatus,
    ExecutionType,
    can_transition,
)
from agent.tool_registry import (
    assert_tool_authorized,
    get_tool_definition,
    registry_contract_snapshot,
    tool_allows_retry,
)
from database.connection import get_session, init_db, reset_engine
from repositories import audit_repository
from services.errors import AppError


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "exec_engine.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("config.DATABASE_URL", url)
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    reset_engine()
    init_db()
    yield
    reset_engine()


def test_execution_creation_and_plan():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="Explain recommendation REC-1",
        recommendation_id="REC-1",
        actor="alex.store",
    )
    assert ex["status"] == ExecutionStatus.CREATED.value
    assert ex["execution_id"].startswith("RUN-")
    assert ex["version"] == 1
    assert ex["correlation_id"]
    env = ex["envelope"]
    assert env["goal"]
    assert env["plan"]["steps"]
    assert any(s["action"] == "get_recommendation" for s in env["plan"]["steps"])


def test_valid_and_invalid_transitions():
    assert can_transition("created", "planning")
    assert can_transition("running", "waiting_for_human")
    assert can_transition("waiting_for_human", "running")
    assert not can_transition("completed", "running")
    assert not can_transition("failed", "planning")

    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="g",
        recommendation_id="REC-x",
    )
    with pytest.raises(AppError) as err:
        transition_execution(
            ex["execution_id"],
            ExecutionStatus.COMPLETED,
            expected_version=999,
        )
    assert err.value.code == "concurrency_conflict"

    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    assert started["status"] == ExecutionStatus.RUNNING.value
    with pytest.raises(AppError) as bad:
        transition_execution(
            started["execution_id"],
            ExecutionStatus.CREATED,
            expected_version=started["version"],
        )
    assert bad.value.code == "invalid_state_transition"


def test_tool_registry_contract():
    snap = registry_contract_snapshot()
    names = {t["name"] for t in snap}
    assert "get_recommendation" in names
    assert "create_mock_purchase_order" in names
    po = get_tool_definition("create_mock_purchase_order")
    assert po is not None
    assert po.read_only is False
    assert po.requires_authorization is True
    assert po.retryable is False
    assert tool_allows_retry("get_recommendation") is True
    assert tool_allows_retry("create_mock_purchase_order") is False


def test_tool_history_persisted():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="g",
        recommendation_id="REC-tool",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    rec = record_tool_start(
        started["execution_id"],
        tool_name="get_recommendation",
        input_summary={"recommendation_id": "REC-tool"},
    )
    assert rec.status == "started"
    mid = get_execution(started["execution_id"])
    assert mid["status"] == ExecutionStatus.WAITING_FOR_TOOL.value
    assert any(t["tool_call_id"] == rec.tool_call_id for t in mid["envelope"]["tool_history"])

    finished = record_tool_finish(
        started["execution_id"],
        tool_call_id=rec.tool_call_id,
        status="completed",
        output_summary={"recommendation_id": "REC-tool"},
        duration_ms=12,
    )
    assert finished["status"] == ExecutionStatus.RUNNING.value
    hist = finished["envelope"]["tool_history"]
    assert hist[-1]["status"] == "completed"
    assert hist[-1]["duration_ms"] == 12


def test_retryable_and_non_retryable_failures():
    retryable = classify_failure(code="model_timeout", attempt=1)
    assert retryable.retryable is True
    assert retryable.code == FailureClass.MODEL_TIMEOUT

    denied = classify_failure(code="authorization_denied")
    assert denied.retryable is False

    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="g",
        recommendation_id="REC-retry",
        max_attempts=3,
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    rec = record_tool_start(
        started["execution_id"],
        tool_name="get_recommendation",
        input_summary={},
    )
    pending = record_tool_finish(
        started["execution_id"],
        tool_call_id=rec.tool_call_id,
        status="failed",
        error=retryable,
    )
    assert pending["status"] == ExecutionStatus.RETRY_PENDING.value

    # Exhaust retries via schedule_retry / fail
    running = transition_execution(
        pending["execution_id"],
        ExecutionStatus.RUNNING,
        expected_version=pending["version"],
    )
    for _ in range(5):
        current = get_execution(running["execution_id"])
        assert current is not None
        if current["status"] == ExecutionStatus.FAILED.value:
            break
        if current["status"] == ExecutionStatus.RETRY_PENDING.value:
            running = transition_execution(
                current["execution_id"],
                ExecutionStatus.RUNNING,
                expected_version=current["version"],
            )
            continue
        rec2 = record_tool_start(
            running["execution_id"],
            tool_name="get_recommendation",
            input_summary={},
            attempt_number=current["attempt_count"] + 1,
        )
        running = record_tool_finish(
            running["execution_id"],
            tool_call_id=rec2.tool_call_id,
            status="failed",
            error=classify_failure(code="model_timeout", attempt=current["attempt_count"] + 1),
        )
    final = get_execution(ex["execution_id"])
    assert final is not None
    assert final["status"] in {
        ExecutionStatus.FAILED.value,
        ExecutionStatus.RETRY_PENDING.value,
    }

    # Non-retryable write tool fails immediately
    ex2 = create_execution(
        execution_type=ExecutionType.ORDER_EXECUTION,
        goal="order",
        recommendation_id="REC-nr",
    )
    s2 = start_execution(ex2["execution_id"], expected_version=ex2["version"])
    t = record_tool_start(
        s2["execution_id"],
        tool_name="create_mock_purchase_order",
        input_summary={"approval_id": "APR-1"},
    )
    failed = record_tool_finish(
        s2["execution_id"],
        tool_call_id=t.tool_call_id,
        status="failed",
        error=classify_failure(code="temporary_provider_failure"),
    )
    # create_mock_purchase_order is not retryable even if error class is
    assert failed["status"] == ExecutionStatus.FAILED.value


def test_waiting_for_human_and_resume_idempotent():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="generic wait",
        recommendation_id="REC-wait",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    waiting = mark_waiting_for_human(
        started["execution_id"],
        expected_version=started["version"],
        reason="Need planner confirmation",
        requested_action="confirm_explanation",
        required_role="store_manager",
        actor="agent",
    )
    assert waiting["status"] == ExecutionStatus.WAITING_FOR_HUMAN.value
    assert waiting["waiting_reason"]

    # Simulate process restart: discard memory, reload from DB
    eid = waiting["execution_id"]
    version = waiting["version"]
    reset_view = get_execution(eid)
    assert reset_view is not None
    assert reset_view["status"] == ExecutionStatus.WAITING_FOR_HUMAN.value
    assert reset_view["version"] == version

    resumed = resume_agent_execution(
        eid,
        actor="alex.store",
        actor_role="store_manager",
        resume_payload={"approve": True},
        expected_version=version,
    )
    assert resumed["status"] == ExecutionStatus.COMPLETED.value

    again = resume_agent_execution(
        eid,
        actor="alex.store",
        actor_role="store_manager",
        resume_payload={"approve": True},
    )
    assert again["status"] == "completed"
    assert again.get("mode") == "idempotent_reload"


def test_stale_concurrency_rejected():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="g",
        recommendation_id="REC-conc",
    )
    start_execution(ex["execution_id"], expected_version=ex["version"])
    with pytest.raises(AppError) as err:
        transition_execution(
            ex["execution_id"],
            ExecutionStatus.COMPLETED,
            expected_version=ex["version"],  # stale
        )
    assert err.value.code == "concurrency_conflict"


def test_execution_references_recommendation_id_not_copy():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="Explain REC-ABC",
        recommendation_id="REC-ABC",
    )
    assert ex["recommendation_id"] == "REC-ABC"
    # Envelope must not embed a full authoritative recommendation blob
    assert "agent_recommended_quantity" not in ex["envelope"].get("context", {})


def test_secret_sanitization_in_tool_summary():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="g",
        recommendation_id="REC-sec",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    rec = record_tool_start(
        started["execution_id"],
        tool_name="get_recommendation",
        input_summary={"api_key": "sk-secret", "recommendation_id": "REC-sec"},
    )
    mid = get_execution(started["execution_id"])
    hist = mid["envelope"]["tool_history"]
    entry = next(t for t in hist if t["tool_call_id"] == rec.tool_call_id)
    assert entry["input_summary"]["api_key"] == "[redacted]"
    assert entry["input_summary"]["recommendation_id"] == "REC-sec"


def test_audit_events_for_lifecycle():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="g",
        recommendation_id="REC-aud",
        actor="alex.store",
    )
    start_execution(ex["execution_id"], expected_version=ex["version"], actor="alex.store")
    with get_session() as session:
        events = audit_repository.list_audit_events(
            session, run_id=ex["execution_id"], limit=50
        )
    types = [e.event_type for e in events]
    assert "agent_execution_created" in types
    assert "agent_execution_planned" in types
    assert "agent_execution_started" in types


def test_full_execution_create_tool_wait_resume_complete():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="full path",
        recommendation_id="REC-full",
    )
    assert ex["status"] == "created"
    running = start_execution(ex["execution_id"], expected_version=ex["version"])
    assert running["status"] == "running"
    tool = record_tool_start(
        running["execution_id"],
        tool_name="get_policy_evaluation",
        input_summary={"recommendation_id": "REC-full"},
    )
    after_tool = record_tool_finish(
        running["execution_id"],
        tool_call_id=tool.tool_call_id,
        status="completed",
        output_summary={"disposition": "human_review"},
    )
    waiting = mark_waiting_for_human(
        after_tool["execution_id"],
        expected_version=after_tool["version"],
        reason="Confirm explanation",
        requested_action="confirm",
    )
    assert waiting["status"] == "waiting_for_human"
    # Reload as if process restarted
    reloaded = get_execution(waiting["execution_id"])
    done = resume_agent_execution(
        reloaded["execution_id"],
        actor="alex.store",
        actor_role="store_manager",
        resume_payload={"approve": True},
        expected_version=reloaded["version"],
    )
    assert done["status"] == "completed"
    final = get_execution(ex["execution_id"])
    assert final["status"] == "completed"
    assert len(final["envelope"]["tool_history"]) >= 1


def test_tool_authorization_registry_gate():
    with pytest.raises(AppError) as err:
        assert_tool_authorized(
            "create_mock_purchase_order",
            actor_role="viewer",
        )
    assert err.value.code == "authorization_denied"


def test_openai_disabled_follow_up_still_creates_execution(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    monkeypatch.setattr("config.OPENAI_API_KEY", "")
    from services import batch_run_service, policy_service
    from agent.runner import answer_follow_up

    policy_service.ensure_default_policy()
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    rec_id = run["recommendation_ids"][0]
    answer = answer_follow_up(
        rec_id,
        "Why was this recommended?",
        user_id="alex.store",
        actor="alex.store",
        actor_role="store_manager",
    )
    assert answer.get("can_change_business_state") is False
    # Deterministic path should not invent a mutation
    assert "status" in answer or "answer" in answer or "summary" in answer


def test_model_cannot_directly_approve_via_registry():
    """Workflow: approval is a service concern; registry marks write tools."""
    meta = get_tool_definition("create_approval_request")
    assert meta is not None
    assert meta.read_only is False
    assert meta.requires_authorization is True
    po = get_tool_definition("create_mock_purchase_order")
    assert po.retryable is False


def test_scenario_remains_hypothetical_in_plan():
    ex = create_execution(
        execution_type=ExecutionType.SCENARIO_ANALYSIS,
        goal="What if order 60?",
        recommendation_id="REC-sc",
    )
    steps = [s["action"] for s in ex["envelope"]["plan"]["steps"]]
    assert "evaluate_quantity_or_delay_scenario" in steps
    assert "create_mock_purchase_order" not in steps

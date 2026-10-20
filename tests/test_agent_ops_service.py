"""Agent Operations service / repository query tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.execution_engine import (
    complete_execution,
    create_execution,
    fail_execution,
    get_execution,
    mark_waiting_for_human,
    record_model_turn_end,
    record_model_turn_start,
    record_tool_finish,
    record_tool_start,
    start_execution,
)
from agent.execution_failures import ExecutionFailure
from agent.execution_states import (
    AUDIT_EXECUTION_CREATED,
    ExecutionStatus,
    ExecutionType,
)
from database.connection import get_session
from repositories import audit_repository
from services import agent_ops_service


def _make_completed(*, recommendation_id: str = "REC-ops-1", user_id: str = "admin.demo"):
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="ops completed",
        recommendation_id=recommendation_id,
        user_id=user_id,
        actor=user_id,
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    t0 = record_tool_start(
        started["execution_id"],
        tool_name="get_recommendation",
        input_summary={"recommendation_id": recommendation_id},
    )
    current = record_tool_finish(
        started["execution_id"],
        tool_call_id=t0.tool_call_id,
        status="completed",
        output_summary={"ok": True},
        duration_ms=41,
    )
    t1 = record_tool_start(
        current["execution_id"],
        tool_name="get_recommendation",
        input_summary={"recommendation_id": recommendation_id, "again": True},
    )
    current = record_tool_finish(
        current["execution_id"],
        tool_call_id=t1.tool_call_id,
        status="completed",
        output_summary={"ok": True},
        duration_ms=27,
    )
    turn = record_model_turn_start(current["execution_id"], model_name="gpt-test")
    record_model_turn_end(
        current["execution_id"],
        turn_id=turn.turn_id,
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
    )
    current = get_execution(current["execution_id"])
    assert current is not None
    return complete_execution(
        current["execution_id"],
        expected_version=current["version"],
        result={"summary": "done"},
    )


def _make_waiting():
    ex = create_execution(
        execution_type=ExecutionType.ORDER_EXECUTION,
        goal="ops waiting",
        recommendation_id="REC-wait-ops",
        approval_id="APR-wait-ops",
        user_id="alex.store",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    return mark_waiting_for_human(
        started["execution_id"],
        expected_version=started["version"],
        reason="Need approval",
        requested_action="create_mock_purchase_order",
        required_role="store_manager",
        actor="agent",
    )


def _make_failed():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="ops failed",
        recommendation_id="REC-fail-ops",
        user_id="admin.demo",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    t0 = record_tool_start(
        started["execution_id"],
        tool_name="get_policy_evaluation",
        input_summary={"recommendation_id": "REC-fail-ops"},
    )
    err = ExecutionFailure(
        code="safe_read_timeout",
        message="boom",
        retryable=True,
        source="tool",
    )
    current = record_tool_finish(
        started["execution_id"],
        tool_call_id=t0.tool_call_id,
        status="failed",
        error=err,
    )
    # May already be retry_pending; force failed for KPI fixture when needed
    current = get_execution(current["execution_id"])
    assert current is not None
    if current["status"] == ExecutionStatus.FAILED.value:
        return current
    return fail_execution(
        current["execution_id"],
        expected_version=current["version"],
        error=ExecutionFailure(
            code="unknown",
            message="boom",
            retryable=False,
            source="execution",
        ),
    )


def test_list_executions_newest_first_and_bounded():
    first = _make_completed(recommendation_id="REC-a")
    second = _make_completed(recommendation_id="REC-b")
    rows = agent_ops_service.list_agent_executions(limit=100)
    assert len(rows) >= 2
    ids = [r["execution_id"] for r in rows]
    assert ids.index(second["execution_id"]) < ids.index(first["execution_id"])
    bounded = agent_ops_service.list_agent_executions(limit=1)
    assert len(bounded) == 1


def test_status_type_recommendation_user_time_filters():
    done = _make_completed(recommendation_id="REC-filt", user_id="dana.admin")
    waiting = _make_waiting()
    failed = _make_failed()

    by_status = agent_ops_service.list_agent_executions(
        statuses=[ExecutionStatus.COMPLETED.value]
    )
    assert all(r["status"] == "completed" for r in by_status)
    assert any(r["execution_id"] == done["execution_id"] for r in by_status)

    by_type = agent_ops_service.list_agent_executions(
        execution_types=[ExecutionType.ORDER_EXECUTION.value]
    )
    assert any(r["execution_id"] == waiting["execution_id"] for r in by_type)

    by_rec = agent_ops_service.list_agent_executions(recommendation_id="REC-filt")
    assert len(by_rec) >= 1
    assert all(r["recommendation_id"] == "REC-filt" for r in by_rec)

    by_user = agent_ops_service.list_agent_executions(user_id="dana.admin")
    assert any(r["execution_id"] == done["execution_id"] for r in by_user)

    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert agent_ops_service.list_agent_executions(started_after=future) == []

    assert any(
        r["execution_id"] == failed["execution_id"]
        for r in agent_ops_service.list_agent_executions(
            statuses=[ExecutionStatus.FAILED.value]
        )
    )


def test_pagination():
    for i in range(3):
        _make_completed(recommendation_id=f"REC-page-{i}")
    page0 = agent_ops_service.list_agent_executions(limit=2, offset=0)
    page1 = agent_ops_service.list_agent_executions(limit=2, offset=2)
    assert len(page0) == 2
    ids0 = {r["execution_id"] for r in page0}
    ids1 = {r["execution_id"] for r in page1}
    assert ids0.isdisjoint(ids1)


def test_operations_metrics_kpis_and_empty():
    empty = agent_ops_service.get_operations_metrics()
    assert empty["active_executions"] == 0
    assert empty["waiting_for_human"] == 0
    assert empty["failed_executions"] == 0
    assert empty["completed_today"] == 0
    assert empty["average_execution_duration_seconds"] is None

    _make_completed()
    waiting = _make_waiting()
    _make_failed()
    active = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="still active",
        recommendation_id="REC-active",
    )
    start_execution(active["execution_id"], expected_version=active["version"])

    metrics = agent_ops_service.get_operations_metrics()
    assert metrics["completed_today"] >= 1
    assert metrics["waiting_for_human"] >= 1
    assert metrics["failed_executions"] >= 1
    assert metrics["active_executions"] >= 1
    assert metrics["open_hitl_requests"] >= 1
    assert metrics["average_execution_duration_seconds"] is not None
    assert waiting["status"] == ExecutionStatus.WAITING_FOR_HUMAN.value


def test_execution_detail_tools_model_turns_and_audit():
    done = _make_completed(recommendation_id="REC-detail")
    detail = agent_ops_service.get_agent_execution_detail(done["execution_id"])
    assert detail is not None
    assert detail["execution_id"] == done["execution_id"]
    tools = detail["tool_history"]
    assert len(tools) >= 2
    assert sum(1 for t in tools if t["tool_name"] == "get_recommendation") >= 2
    turns = detail["model_turns"]
    assert turns
    assert turns[0]["input_tokens"] == 10
    assert turns[0]["total_tokens"] == 30
    assert "chain_of_thought" not in str(detail)
    assert detail["timeline"]
    assert detail["audit_events"]
    assert any(
        e["event_type"] == AUDIT_EXECUTION_CREATED for e in detail["audit_events"]
    )


def test_missing_tokens_safe_and_failed_tool_retryable():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="tokens",
        recommendation_id="REC-tok",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    turn = record_model_turn_start(started["execution_id"], model_name="gpt-test")
    record_model_turn_end(started["execution_id"], turn_id=turn.turn_id)
    t0 = record_tool_start(
        started["execution_id"],
        tool_name="get_policy_evaluation",
        input_summary={"x": 1},
    )
    record_tool_finish(
        started["execution_id"],
        tool_call_id=t0.tool_call_id,
        status="failed",
        error=ExecutionFailure(
            code="safe_read_timeout",
            message="slow",
            retryable=True,
            source="tool",
        ),
    )
    detail = agent_ops_service.get_agent_execution_detail(started["execution_id"])
    assert detail["model_turns"][0]["input_tokens"] is None
    assert detail["model_turns"][0]["total_tokens"] is None
    failed_tools = [t for t in detail["tool_history"] if t["status"] == "failed"]
    assert failed_tools
    assert failed_tools[0]["retryable"] is True


def test_execution_audit_does_not_mix_batch_run_events():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="audit mix",
        recommendation_id="REC-mix",
    )
    batch_run_id = "RUN-batchmix01"
    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "batch_started",
            actor="replenishment_scheduler",
            run_id=batch_run_id,
            details={"note": "batch only"},
        )
        audit_repository.write_audit_event(
            session,
            "batch_completed",
            actor="replenishment_scheduler",
            run_id=ex["execution_id"],
            details={"should": "exclude"},
        )
    events = agent_ops_service.list_agent_execution_audit_events(ex["execution_id"])
    assert all(e["run_id"] == ex["execution_id"] for e in events)
    assert all(e["event_type"] != "batch_started" for e in events)
    assert all(e["event_type"] != "batch_completed" for e in events)
    assert agent_ops_service.list_agent_execution_audit_events(batch_run_id) == []


def test_export_csv_safe_and_runtime_health():
    _make_completed()
    csv_text = agent_ops_service.export_execution_summary_csv(limit=10)
    assert "execution_id" in csv_text
    assert "api_key" not in csv_text.lower()
    assert "prompt" not in csv_text.lower()
    runtime = agent_ops_service.get_agent_runtime_health()
    assert runtime["status"] in {"healthy", "degraded", "unavailable"}
    assert "thresholds" in runtime


def test_secret_sanitization_in_detail():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="sec",
        recommendation_id="REC-sec-ops",
    )
    started = start_execution(ex["execution_id"], expected_version=ex["version"])
    record_tool_start(
        started["execution_id"],
        tool_name="get_recommendation",
        input_summary={
            "api_key": "sk-secret-value",
            "OPENAI_API_KEY": "sk-secret-value",
            "recommendation_id": "REC-sec-ops",
        },
    )
    detail = agent_ops_service.get_agent_execution_detail(started["execution_id"])
    dumped = str(detail)
    assert "sk-secret-value" not in dumped
    assert "CRON_SECRET" not in dumped
    assert "DEMO_ACCESS_CODE" not in dumped

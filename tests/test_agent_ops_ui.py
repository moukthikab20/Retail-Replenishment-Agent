"""Agent Operations Streamlit AppTests + role/security checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

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
from agent.execution_states import ExecutionType
from services import agent_ops_service, auth_service

APP_PATH = Path(__file__).parent / "ui_apps" / "agent_ops_app.py"
TIMEOUT = 45


def _seed_ops_data():
    done = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="ui completed",
        recommendation_id="REC-ui-done",
        user_id="admin.demo",
    )
    started = start_execution(done["execution_id"], expected_version=done["version"])
    t0 = record_tool_start(
        started["execution_id"],
        tool_name="get_recommendation",
        input_summary={"recommendation_id": "REC-ui-done"},
    )
    current = record_tool_finish(
        started["execution_id"],
        tool_call_id=t0.tool_call_id,
        status="completed",
        output_summary={"ok": True},
        duration_ms=12,
    )
    t1 = record_tool_start(
        current["execution_id"],
        tool_name="get_policy_evaluation",
        input_summary={"recommendation_id": "REC-ui-done"},
    )
    current = record_tool_finish(
        current["execution_id"],
        tool_call_id=t1.tool_call_id,
        status="failed",
        error=ExecutionFailure(
            code="safe_read_timeout",
            message="simulated",
            retryable=True,
            source="tool",
        ),
    )
    # Move back to running if retry_pending so we can complete for UI fixture
    current = get_execution(current["execution_id"])
    assert current is not None
    turn = record_model_turn_start(current["execution_id"], model_name="gpt-test")
    record_model_turn_end(
        current["execution_id"],
        turn_id=turn.turn_id,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
    )
    current = get_execution(current["execution_id"])
    assert current is not None
    # If retry_pending, transition via complete may fail — force complete from running
    if current["status"] != "running":
        from agent.execution_engine import transition_execution
        from agent.execution_states import ExecutionStatus

        if current["status"] == ExecutionStatus.RETRY_PENDING.value:
            current = transition_execution(
                current["execution_id"],
                ExecutionStatus.RUNNING,
                expected_version=current["version"],
            )
    completed = complete_execution(
        current["execution_id"],
        expected_version=current["version"],
    )

    waiting = create_execution(
        execution_type=ExecutionType.ORDER_EXECUTION,
        goal="ui waiting",
        recommendation_id="REC-ui-wait",
        approval_id="APR-ui-wait",
        user_id="alex.store",
    )
    w_started = start_execution(waiting["execution_id"], expected_version=waiting["version"])
    mark_waiting_for_human(
        w_started["execution_id"],
        expected_version=w_started["version"],
        reason="Need human",
        requested_action="create_mock_purchase_order",
        required_role="store_manager",
    )

    failed = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="ui failed",
        recommendation_id="REC-ui-fail",
    )
    f_started = start_execution(failed["execution_id"], expected_version=failed["version"])
    fail_execution(
        f_started["execution_id"],
        expected_version=f_started["version"],
        error=ExecutionFailure(
            code="unknown",
            message="failed fixture",
            retryable=False,
            source="execution",
        ),
    )
    return {
        "completed_id": completed["execution_id"],
        "waiting_id": w_started["execution_id"],
        "failed_id": f_started["execution_id"],
    }


def _app(role: str = "administrator") -> AppTest:
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["test_role"] = role
    return at


def test_administrator_can_open_agent_operations():
    _seed_ops_data()
    at = _app("administrator")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Agent Operations" in text
    assert "Active Executions" in text
    assert "Waiting for Human" in text
    assert "Scheduler" in text


def test_viewer_cannot_open_agent_operations():
    assert auth_service.can_trigger_batch_run("viewer") is False
    at = _app("viewer")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    warn_text = " ".join(str(w.value) for w in at.warning)
    text = " ".join(str(m.value) for m in at.markdown) + " " + warn_text
    assert "administrators" in text.lower()
    assert "Export Execution Summary CSV" not in text


def test_kpi_table_filters_detail_tools_model_waiting(monkeypatch):
    seeded = _seed_ops_data()
    metrics = agent_ops_service.get_operations_metrics()
    assert metrics["completed_today"] >= 1
    assert metrics["waiting_for_human"] >= 1
    assert metrics["failed_executions"] >= 1

    openai_mock = MagicMock(side_effect=AssertionError("OpenAI must not be called"))
    batch_mock = MagicMock(side_effect=AssertionError("Batch must not be called"))
    monkeypatch.setattr("openai.OpenAI", openai_mock, raising=False)
    monkeypatch.setattr(
        "services.batch_run_service.run_replenishment_batch",
        batch_mock,
        raising=False,
    )

    at = _app("administrator")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Waiting for Human" in text
    assert "Failed / Retry Pending" in text

    status_box = at.selectbox[0]
    status_box.select("completed").run(timeout=TIMEOUT)
    assert not at.exception

    type_box = at.selectbox[1]
    type_box.select("follow_up").run(timeout=TIMEOUT)
    assert not at.exception

    detail_box = at.selectbox[-1]
    options = list(detail_box.options)
    target = next((o for o in options if o == seeded["completed_id"]), None)
    if target is None:
        target = next((o for o in options if o != "(none)"), None)
    if target:
        detail_box.select(target).run(timeout=TIMEOUT)
        assert not at.exception
        detail_text = " ".join(str(m.value) for m in at.markdown)
        assert "Tool History" in detail_text or "Execution Detail" in detail_text
        assert "chain_of_thought" not in detail_text.lower()
        assert "sk-" not in detail_text.lower()
        lowered = detail_text.lower()
        assert "openai_api_key" not in lowered
        assert "cron_secret" not in lowered
        assert "demo_access_code" not in lowered

    openai_mock.assert_not_called()
    batch_mock.assert_not_called()


def test_refresh_does_not_mutate_and_list_bounded(monkeypatch):
    seeded = _seed_ops_data()
    before = agent_ops_service.get_agent_execution_detail(seeded["completed_id"])
    assert before is not None
    version_before = before["version"]

    mutate = MagicMock(side_effect=AssertionError("must not mutate"))
    monkeypatch.setattr("agent.execution_engine.create_execution", mutate, raising=False)
    monkeypatch.setattr("agent.execution_engine.start_execution", mutate, raising=False)

    at = _app("administrator")
    at.run(timeout=TIMEOUT)
    assert not at.exception
    refresh = next(b for b in at.button if b.label == "Refresh")
    refresh.click().run(timeout=TIMEOUT)
    assert not at.exception

    after = agent_ops_service.get_agent_execution_detail(seeded["completed_id"])
    assert after["version"] == version_before
    mutate.assert_not_called()

    rows = agent_ops_service.list_agent_executions(limit=100)
    assert len(rows) <= 100

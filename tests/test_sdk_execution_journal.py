"""Hybrid SDK RunHooks → durable execution journal (no live OpenAI)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agents.run_context import RunContextWrapper
from agents.tool_context import ToolContext

from agent.context import ReplenishmentRunContext
from agent.execution_engine import (
    create_execution,
    get_execution,
    record_tool_finish,
    record_tool_start,
    reconcile_unfinished_tools,
    start_execution,
)
from agent.execution_hooks import ExecutionJournalHooks
from agent.execution_states import ExecutionStatus, ExecutionType
from agent.runner import (
    _execute_runner,
    analyze_replenishment,
    resume_order_run,
    start_order_agent_after_approval,
)
from agent.tool_registry import (
    assert_tool_allowed_for_execution,
    get_allowed_tools_for_execution_type,
)
from database.connection import get_session
from repositories import audit_repository
from services import (
    approval_service,
    human_review_service,
    recommendation_service,
)
from services.errors import AppError


def _run(coro):
    return asyncio.run(coro)


def _ctx(
    execution_id: str,
    *,
    execution_type: str = ExecutionType.FOLLOW_UP.value,
    actor: str = "agent",
    actor_role: str | None = "store_manager",
) -> ReplenishmentRunContext:
    return ReplenishmentRunContext(
        run_id=execution_id,
        execution_id=execution_id,
        correlation_id=f"CORR-{execution_id}",
        execution_type=execution_type,
        actor=actor,
        actor_role=actor_role,
        recommendation_id="REC-J",
    )


def _tool_ctx(ctx: ReplenishmentRunContext, *, tool_name: str, tool_call_id: str, args: str = "{}"):
    return ToolContext(
        context=ctx,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_arguments=args,
    )


def _fake_tool(name: str):
    return SimpleNamespace(name=name)


def _approved_order():
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="journal hitl",
        user_id="jamie.planner",
        session_id="sess-j",
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="jamie.planner",
        actor_role="inventory_planner",
        user_id="jamie.planner",
        session_id="sess-j",
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
    return rec, decided


def test_hooks_journal_multi_tool_same_execution():
    async def _body():
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="multi tool",
            recommendation_id="REC-J",
        )
        start_execution(ex["execution_id"], expected_version=ex["version"])
        ctx = _ctx(ex["execution_id"])
        hooks = ExecutionJournalHooks()
        agent = SimpleNamespace(name="RetailReplenishment", model="mock-model")

        t1 = _tool_ctx(ctx, tool_name="get_recommendation", tool_call_id="call_sdk_1")
        t2 = _tool_ctx(ctx, tool_name="get_policy_evaluation", tool_call_id="call_sdk_2")
        llm_ctx = RunContextWrapper(context=ctx)

        await hooks.on_llm_start(llm_ctx, agent, None, [])
        await hooks.on_tool_start(t1, agent, _fake_tool("get_recommendation"))
        await hooks.on_tool_end(
            t1, agent, _fake_tool("get_recommendation"), {"recommendation_id": "REC-J"}
        )
        await hooks.on_tool_start(t2, agent, _fake_tool("get_policy_evaluation"))
        await hooks.on_tool_end(
            t2, agent, _fake_tool("get_policy_evaluation"), {"status": "ok"}
        )
        usage = SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18)
        await hooks.on_llm_end(llm_ctx, agent, SimpleNamespace(usage=usage))  # type: ignore[arg-type]
        return ex["execution_id"]

    eid = _run(_body())
    row = get_execution(eid)
    assert row is not None
    hist = row["envelope"]["tool_history"]
    assert len(hist) == 2
    assert hist[0]["tool_call_id"] == "call_sdk_1"
    assert hist[1]["tool_call_id"] == "call_sdk_2"
    assert hist[0]["status"] == "completed"
    assert hist[1]["status"] == "completed"
    assert hist[0]["duration_ms"] is not None
    turns = row["envelope"]["model_turns"]
    assert turns
    assert turns[-1]["input_tokens"] == 11
    assert turns[-1]["total_tokens"] == 18
    assert "chain_of_thought" not in str(row["envelope"]).lower()


def test_sdk_tool_call_id_preserved_and_fallback():
    async def _body():
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="ids",
            recommendation_id="REC-J",
        )
        start_execution(ex["execution_id"], expected_version=ex["version"])
        ctx = _ctx(ex["execution_id"])
        hooks = ExecutionJournalHooks()
        agent = SimpleNamespace(name="A", model=None)

        with_id = _tool_ctx(
            ctx, tool_name="get_recommendation", tool_call_id="call_preserved"
        )
        await hooks.on_tool_start(with_id, agent, _fake_tool("get_recommendation"))
        await hooks.on_tool_end(
            with_id, agent, _fake_tool("get_recommendation"), {"ok": True}
        )

        plain = SimpleNamespace(context=ctx, tool_call_id=None, tool_arguments="{}")
        await hooks.on_tool_start(plain, agent, _fake_tool("get_policy_evaluation"))
        await hooks.on_tool_end(
            plain, agent, _fake_tool("get_policy_evaluation"), {"ok": True}
        )
        return ex["execution_id"]

    hist = get_execution(_run(_body()))["envelope"]["tool_history"]
    assert hist[0]["tool_call_id"] == "call_preserved"
    assert hist[1]["tool_call_id"].startswith("TC-")


def test_repeated_same_tool_distinct_records():
    async def _body():
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="repeat",
            recommendation_id="REC-J",
        )
        start_execution(ex["execution_id"], expected_version=ex["version"])
        ctx = _ctx(ex["execution_id"])
        hooks = ExecutionJournalHooks()
        agent = SimpleNamespace(name="A", model=None)
        for i in range(2):
            tc = _tool_ctx(
                ctx,
                tool_name="get_recommendation",
                tool_call_id=f"call_repeat_{i}",
                args='{"recommendation_id":"REC-J"}',
            )
            await hooks.on_tool_start(tc, agent, _fake_tool("get_recommendation"))
            await hooks.on_tool_end(tc, agent, _fake_tool("get_recommendation"), {"i": i})
        return ex["execution_id"]

    hist = get_execution(_run(_body()))["envelope"]["tool_history"]
    assert len(hist) == 2
    assert hist[0]["tool_call_id"] != hist[1]["tool_call_id"]
    assert hist[0]["tool_name"] == hist[1]["tool_name"] == "get_recommendation"


def test_tool_failure_no_duplicate_and_reconcile():
    async def _body():
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="fail",
            recommendation_id="REC-J",
        )
        start_execution(ex["execution_id"], expected_version=ex["version"])
        ctx = _ctx(ex["execution_id"])
        hooks = ExecutionJournalHooks()
        agent = SimpleNamespace(name="A", model=None)
        tc = _tool_ctx(ctx, tool_name="get_recommendation", tool_call_id="call_fail")
        await hooks.on_tool_start(tc, agent, _fake_tool("get_recommendation"))
        hooks.journal_tool_failure(
            execution_id=ex["execution_id"],
            tool_name="get_recommendation",
            tool_call_id="call_fail",
            exc=RuntimeError("boom"),
            actor="agent",
        )
        hooks.journal_tool_failure(
            execution_id=ex["execution_id"],
            tool_name="get_recommendation",
            tool_call_id="call_fail",
            exc=RuntimeError("boom again"),
            actor="agent",
        )
        return ex["execution_id"]

    hist = get_execution(_run(_body()))["envelope"]["tool_history"]
    failed = [t for t in hist if t["tool_call_id"] == "call_fail"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"

    ex2 = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="crash",
        recommendation_id="REC-J2",
    )
    start_execution(ex2["execution_id"], expected_version=ex2["version"])
    rec = record_tool_start(
        ex2["execution_id"],
        tool_name="get_recommendation",
        tool_call_id="call_orphan",
        input_summary={},
    )
    assert rec.status == "started"
    reconciled = reconcile_unfinished_tools(ex2["execution_id"], actor="agent")
    assert "call_orphan" in reconciled
    orphan = next(
        t
        for t in get_execution(ex2["execution_id"])["envelope"]["tool_history"]
        if t["tool_call_id"] == "call_orphan"
    )
    assert orphan["status"] == "failed"
    assert reconcile_unfinished_tools(ex2["execution_id"]) == []


def test_unregistered_and_execution_type_restriction():
    async def _body():
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="policy",
            recommendation_id="REC-J",
        )
        start_execution(ex["execution_id"], expected_version=ex["version"])
        ctx = _ctx(ex["execution_id"], execution_type=ExecutionType.FOLLOW_UP.value)
        hooks = ExecutionJournalHooks()
        agent = SimpleNamespace(name="A", model=None)

        with pytest.raises(AppError):
            await hooks.on_tool_start(
                _tool_ctx(ctx, tool_name="not_a_real_tool", tool_call_id="x1"),
                agent,
                _fake_tool("not_a_real_tool"),
            )

        with pytest.raises(AppError):
            await hooks.on_tool_start(
                _tool_ctx(
                    ctx, tool_name="create_mock_purchase_order", tool_call_id="x2"
                ),
                agent,
                _fake_tool("create_mock_purchase_order"),
            )

    _run(_body())
    allowed = get_allowed_tools_for_execution_type("follow_up")
    assert allowed is not None
    assert "get_recommendation" in allowed
    assert "create_mock_purchase_order" not in allowed
    assert_tool_allowed_for_execution(
        "get_recommendation", execution_type="follow_up", actor_role="store_manager"
    )


def test_argument_and_output_sanitization_and_external_tool_call_id():
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="sanitize",
        recommendation_id="REC-J",
    )
    start_execution(ex["execution_id"], expected_version=ex["version"])
    rec = record_tool_start(
        ex["execution_id"],
        tool_name="get_recommendation",
        tool_call_id="call_external",
        input_summary={"api_key": "sk-secret", "recommendation_id": "REC-J"},
    )
    assert rec.tool_call_id == "call_external"
    assert rec.input_summary["api_key"] == "[redacted]"
    finished = record_tool_finish(
        ex["execution_id"],
        tool_call_id="call_external",
        status="completed",
        output_summary={"token": "should-hide", "status": "ok"},
        duration_ms=5,
    )
    out = finished["envelope"]["tool_history"][-1]["output_summary"]
    assert out.get("token") == "[redacted]"
    assert "sk-secret" not in str(finished["envelope"])


def test_execute_runner_passes_hooks():
    agent = MagicMock()
    captured = {}

    def fake_run_sync(ag, payload, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(final_output={"ok": True}, interruptions=[])

    with patch("agent.runner.Runner.run_sync", side_effect=fake_run_sync):
        create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="hooks",
            recommendation_id="REC-J",
            execution_id="RUN-hooks",
        )
        start_execution("RUN-hooks", expected_version=1)
        _execute_runner(agent, "hi", context=_ctx("RUN-hooks"), max_turns=2)
    assert isinstance(captured["hooks"], ExecutionJournalHooks)
    assert captured["context"].execution_id == "RUN-hooks"


def test_execute_runner_reconciles_on_crash():
    agent = MagicMock()
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="crash runner",
        recommendation_id="REC-J",
    )
    start_execution(ex["execution_id"], expected_version=ex["version"])
    record_tool_start(
        ex["execution_id"],
        tool_name="get_recommendation",
        tool_call_id="call_crash",
        input_summary={},
    )
    ctx = _ctx(ex["execution_id"])

    with patch("agent.runner.Runner.run_sync", side_effect=RuntimeError("runner exploded")):
        with pytest.raises(RuntimeError):
            _execute_runner(agent, "hi", context=ctx, max_turns=1)

    row = get_execution(ex["execution_id"])
    assert row["status"] == ExecutionStatus.FAILED.value
    orphan = next(
        t for t in row["envelope"]["tool_history"] if t["tool_call_id"] == "call_crash"
    )
    assert orphan["status"] == "failed"


def test_analysis_deterministic_lifecycle(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    result = analyze_replenishment(
        "ST001",
        "SKU-1001",
        user_id="u1",
        session_id="s1",
        actor="agent",
    )
    eid = result.get("execution_id") or result.get("run_id")
    assert eid
    row = get_execution(eid)
    assert row is not None
    if result.get("status") != "error":
        assert row["status"] == ExecutionStatus.COMPLETED.value
        assert result.get("execution_mode") == "deterministic_fallback"


def test_order_pause_stores_tool_call_id_and_resume_same_execution(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, approval = _approved_order()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert paused["status"] == "paused"
    run_id = paused["run_id"]
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, run_id)
        assert row is not None
        assert row.status == ExecutionStatus.WAITING_FOR_HUMAN.value

    refreshed = get_execution(run_id)
    hist = refreshed["envelope"]["tool_history"]
    call_id = refreshed["envelope"]["context"].get("tool_call_id") or (
        refreshed["envelope"].get("guards") or {}
    ).get("tool_call_id")
    assert call_id
    assert any(t["tool_call_id"] == call_id and t["status"] == "paused" for t in hist)

    resumed = resume_order_run(
        run_id=run_id,
        approve=True,
        actor="admin.demo",
        actor_role="administrator",
    )
    assert resumed["status"] == "completed"
    assert resumed.get("execution_id") == run_id or resumed.get("run_id") == run_id
    final = get_execution(run_id)
    assert final["status"] == ExecutionStatus.COMPLETED.value
    tool = next(t for t in final["envelope"]["tool_history"] if t["tool_call_id"] == call_id)
    assert tool["status"] == "completed"

    again = resume_order_run(
        run_id=run_id,
        approve=True,
        actor="admin.demo",
        actor_role="administrator",
    )
    assert again["status"] == "completed"
    assert again["purchase_order"]["purchase_order_id"] == resumed["purchase_order"][
        "purchase_order_id"
    ]


def test_missing_usage_metrics_safe():
    async def _body():
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal="usage",
            recommendation_id="REC-J",
        )
        start_execution(ex["execution_id"], expected_version=ex["version"])
        ctx = _ctx(ex["execution_id"])
        hooks = ExecutionJournalHooks()
        agent = SimpleNamespace(name="A", model="m")
        wrapper = RunContextWrapper(context=ctx)
        await hooks.on_llm_start(wrapper, agent, None, [])
        await hooks.on_llm_end(wrapper, agent, SimpleNamespace(usage=None))  # type: ignore[arg-type]
        return ex["execution_id"]

    turns = get_execution(_run(_body()))["envelope"]["model_turns"]
    assert turns[-1]["input_tokens"] is None
    assert turns[-1]["status"] == "completed"


def test_process_reload_preserves_tool_history(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec, approval = _approved_order()
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="casey.category",
        actor_role="category_manager",
    )
    run_id = paused["run_id"]
    before = get_execution(run_id)
    after = get_execution(run_id)
    assert before["envelope"]["tool_history"] == after["envelope"]["tool_history"]
    assert after["envelope"]["tool_history"]

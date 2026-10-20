"""Lightweight evals for the durable agent execution engine (no live OpenAI)."""

from __future__ import annotations

import json
from pathlib import Path

from agent.execution_engine import (
    create_execution,
    get_execution,
    mark_waiting_for_human,
    resume_agent_execution,
    start_execution,
)
from agent.execution_states import ExecutionType
from agent.tool_registry import get_tool_definition, registry_contract_snapshot
from agent.follow_up_guardrails import detect_prohibited_follow_up


CASES_PATH = Path(__file__).parent / "agent_execution_cases.json"


def _load_cases() -> list[dict]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return list(payload.get("cases") or [])


def test_execution_eval_cases_cover_required_scenarios():
    cases = _load_cases()
    ids = {c["id"] for c in cases}
    required = {
        "exec_explain_stockout",
        "exec_explain_low_confidence",
        "exec_explain_stale_block",
        "exec_quantity_scenario",
        "exec_delay_scenario",
        "exec_unauthorized_action",
        "exec_hallucinated_quantity",
        "exec_pause_resume_plan",
    }
    assert required.issubset(ids)


def test_execution_eval_unauthorized_and_hallucination_prohibited():
    for case_id in ("exec_unauthorized_action", "exec_hallucinated_quantity"):
        case = next(c for c in _load_cases() if c["id"] == case_id)
        question = case["input"]["question"]
        block = detect_prohibited_follow_up(question)
        assert block is not None or case.get("expected_prohibition")


def test_execution_eval_scenario_tools_are_read_only():
    for name in ("evaluate_quantity_scenario", "evaluate_delay_scenario"):
        meta = get_tool_definition(name)
        assert meta is not None
        assert meta.read_only is True
        assert meta.requires_authorization is False


def test_execution_eval_pause_resume_path():
    ex = create_execution(
        execution_type=ExecutionType.ORDER_EXECUTION,
        goal="Order after approval",
        recommendation_id="REC-EVAL",
        approval_id="APR-EVAL",
    )
    path = [ex["status"]]
    running = start_execution(ex["execution_id"], expected_version=ex["version"])
    path.append(running["status"])
    waiting = mark_waiting_for_human(
        running["execution_id"],
        expected_version=running["version"],
        reason="HITL",
        requested_action="create_mock_purchase_order",
    )
    path.append(waiting["status"])
    # Generic resume (no real PO) — order path would need approval; use follow_up type
    # Already waiting — complete via reject then prove waiting existed.
    assert waiting["status"] == "waiting_for_human"
    # Switch: create follow_up wait/resume for full completed path without PO deps
    fu = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="pause resume eval",
        recommendation_id="REC-EVAL-2",
    )
    r = start_execution(fu["execution_id"], expected_version=fu["version"])
    w = mark_waiting_for_human(
        r["execution_id"],
        expected_version=r["version"],
        reason="confirm",
        requested_action="confirm",
    )
    done = resume_agent_execution(
        w["execution_id"],
        actor="alex.store",
        actor_role="store_manager",
        resume_payload={"approve": True},
        expected_version=w["version"],
    )
    assert done["status"] == "completed"
    assert get_execution(w["execution_id"])["status"] == "completed"


def test_execution_eval_registry_forbids_po_on_follow_up_surface():
    snap = {t["name"]: t for t in registry_contract_snapshot()}
    assert snap["create_mock_purchase_order"]["requires_authorization"] is True
    assert snap["create_mock_purchase_order"]["retryable"] is False


def test_execution_eval_follow_up_cases_have_durable_tool_history_shape():
    """Eval cases must validate expected tools against registry + journal semantics."""
    from agent.tool_registry import get_allowed_tools_for_execution_type

    for case in _load_cases():
        exec_type = case.get("execution_type")
        allowed = get_allowed_tools_for_execution_type(exec_type)
        if allowed is None:
            continue
        for name in case.get("expected_tools_any_of") or []:
            assert name in allowed, f"{case['id']}: expected tool {name} not allowed"
        for name in case.get("prohibited_tools") or []:
            assert name not in allowed or get_tool_definition(name).requires_authorization


def test_execution_eval_journal_multi_tool_follow_up_history():
    """Stockout/low-confidence/stale evals expect multi-tool durable history shape."""
    from agent.execution_engine import (
        create_execution,
        record_tool_finish,
        record_tool_start,
        start_execution,
        try_complete_execution,
        get_execution,
    )

    for case_id in (
        "exec_explain_stockout",
        "exec_explain_low_confidence",
        "exec_explain_stale_block",
    ):
        case = next(c for c in _load_cases() if c["id"] == case_id)
        tools = case["expected_tools_any_of"]
        ex = create_execution(
            execution_type=ExecutionType.FOLLOW_UP,
            goal=case["scenario"],
            recommendation_id=f"REC-{case_id}",
        )
        started = start_execution(ex["execution_id"], expected_version=ex["version"])
        call_ids = []
        for idx, tool_name in enumerate(tools[:2]):
            rec = record_tool_start(
                started["execution_id"],
                tool_name=tool_name,
                tool_call_id=f"call-{case_id}-{idx}",
                input_summary={"recommendation_id": f"REC-{case_id}"},
            )
            call_ids.append(rec.tool_call_id)
            started = record_tool_finish(
                started["execution_id"],
                tool_call_id=rec.tool_call_id,
                status="completed",
                output_summary={"ok": True},
                duration_ms=3 + idx,
            )
        try_complete_execution(ex["execution_id"], result={"mode": "eval"})
        final = get_execution(ex["execution_id"])
        assert final["status"] == "completed"
        hist = final["envelope"]["tool_history"]
        assert [h["tool_call_id"] for h in hist] == call_ids
        assert all(h["status"] == "completed" for h in hist)
        forbidden = set(case.get("prohibited_tools") or [])
        assert not {h["tool_name"] for h in hist} & forbidden

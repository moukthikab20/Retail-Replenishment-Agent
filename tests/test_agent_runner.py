"""Checkpoint 4 — runner APIs, sessions, tracing, and controlled errors."""

from __future__ import annotations

import asyncio
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agents import MaxTurnsExceeded, OutputGuardrailTripwireTriggered, RunConfig, ToolTimeoutError

from agent.context import ReplenishmentRunContext
from agent.runner import (
    _build_run_config,
    _execute_runner,
    analyze_replenishment,
    answer_follow_up,
    follow_up_conversation_id,
    resume_order_flow,
    resume_order_run,
    run_analysis,
)
from agent.schemas import FollowUpAnswer, ReplenishmentAgentDecision
from config import TRACE_INCLUDE_SENSITIVE_DATA, WORKFLOW_ANALYSIS, WORKFLOW_FOLLOW_UP
from services import recommendation_service


def test_public_aliases_point_to_new_apis():
    assert run_analysis is analyze_replenishment
    assert resume_order_flow is resume_order_run


def test_context_has_no_secret_fields():
    names = {f.name for f in fields(ReplenishmentRunContext)}
    for banned in {"api_key", "openai_api_key", "password", "secret", "token"}:
        assert banned not in names
    ctx = ReplenishmentRunContext(
        run_id="RUN-1",
        user_id="alex.store",
        session_id="sess-1",
        conversation_id="replenishment:alex.store:rec-1",
    )
    assert ctx.user_id == "alex.store"
    assert not hasattr(ctx, "api_key")


def test_run_config_defaults_hide_sensitive_data():
    cfg = _build_run_config(
        workflow_name=WORKFLOW_ANALYSIS,
        group_id="g1",
        trace_metadata={"run_id": "RUN-1"},
    )
    assert isinstance(cfg, RunConfig)
    assert cfg.workflow_name == WORKFLOW_ANALYSIS
    assert cfg.trace_include_sensitive_data is TRACE_INCLUDE_SENSITIVE_DATA
    assert TRACE_INCLUDE_SENSITIVE_DATA is False
    assert cfg.trace_metadata["run_id"] == "RUN-1"


def test_analyze_replenishment_deterministic_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = analyze_replenishment(
        "ST001",
        "SKU-1001",
        user_id="alex.store",
        session_id="sess-a",
    )
    assert decision["status"] == "completed"
    assert decision["mode"] == "deterministic_fallback"
    assert decision["recommendation_id"]
    assert isinstance(decision["agent_recommended_quantity"], int)


def test_answer_follow_up_deterministic_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="t", user_id="alex.store", session_id="sess-a"
    )
    result = answer_follow_up(
        rec.recommendation_id,
        "Why is the recommendation this quantity?",
        user_id="alex.store",
        session_id="sess-a",
    )
    assert result["status"] == "completed"
    assert result["mode"] == "deterministic_fallback"
    assert result["recommendation_id"] == rec.recommendation_id
    assert (
        "unavailable" in result["answer"].lower()
        or "api key" in result["answer"].lower()
        or "verified" in result["answer"].lower()
    )
    assert any("agent_recommended_quantity=" in f for f in result["verified_facts"])
    assert result["conversation_id"] == follow_up_conversation_id(
        rec.recommendation_id, user_id="alex.store"
    )
    assert result["follow_up_session_id"] == result["conversation_id"]
    assert result["conversation_id"] == f"replenishment:alex.store:{rec.recommendation_id}"


def test_answer_follow_up_missing_recommendation(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    result = answer_follow_up("REC-does-not-exist", "Why?")
    assert result["status"] == "error"
    assert result["error_code"] == "missing_recommendation"
    assert result["unresolved_items"]


def test_execute_runner_avoids_run_sync_inside_async_loop(monkeypatch):
    calls = {"run": 0, "run_sync": 0}

    async def _fake_run(*_a, **_k):
        calls["run"] += 1
        return SimpleNamespace(final_output={"ok": True}, interruptions=[])

    def _fake_sync(*_a, **_k):
        calls["run_sync"] += 1
        return SimpleNamespace(final_output={"ok": True}, interruptions=[])

    monkeypatch.setattr("agent.runner.Runner.run", _fake_run)
    monkeypatch.setattr("agent.runner.Runner.run_sync", _fake_sync)

    async def _inside():
        return _execute_runner(
            MagicMock(),
            "prompt",
            context=ReplenishmentRunContext(run_id="RUN-x"),
            max_turns=3,
            run_config=_build_run_config(
                workflow_name=WORKFLOW_FOLLOW_UP,
                group_id="g",
                trace_metadata=None,
            ),
        )

    result = asyncio.run(_inside())
    assert result.final_output == {"ok": True}
    assert calls["run"] == 1
    assert calls["run_sync"] == 0


def test_execute_runner_uses_run_sync_outside_loop(monkeypatch):
    calls = {"run_sync": 0}

    def _fake_sync(*_a, **_k):
        calls["run_sync"] += 1
        return SimpleNamespace(final_output={"ok": True}, interruptions=[])

    monkeypatch.setattr("agent.runner.Runner.run_sync", _fake_sync)
    result = _execute_runner(
        MagicMock(),
        "prompt",
        context=ReplenishmentRunContext(run_id="RUN-y"),
        max_turns=3,
        run_config=_build_run_config(
            workflow_name=WORKFLOW_ANALYSIS,
            group_id="g",
            trace_metadata=None,
        ),
    )
    assert result.final_output == {"ok": True}
    assert calls["run_sync"] == 1


def test_analyze_maps_max_turns_and_timeout(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("agent.runner.build_replenishment_agent", MagicMock())

    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: (_ for _ in ()).throw(MaxTurnsExceeded("too many")),
    )
    out = analyze_replenishment("ST001", "SKU-1001")
    assert out["status"] == "error"
    assert out["error_code"] == "max_turns_exceeded"

    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: (_ for _ in ()).throw(ToolTimeoutError("get_demand_forecast", 30.0)),
    )
    out = analyze_replenishment("ST001", "SKU-1001")
    assert out["error_code"] == "model_timeout"


def test_analyze_maps_guardrail_and_malformed_output(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("agent.runner.build_replenishment_agent", MagicMock())

    class _Trip(OutputGuardrailTripwireTriggered):
        def __init__(self) -> None:
            Exception.__init__(self, "tripwire")

    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: (_ for _ in ()).throw(_Trip()),
    )
    out = analyze_replenishment("ST001", "SKU-1001")
    assert out["error_code"] == "guardrail_tripwire"

    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: SimpleNamespace(
            interruptions=[],
            final_output={"not": "a valid decision"},
        ),
    )
    out = analyze_replenishment("ST001", "SKU-1001")
    assert out["status"] == "error"
    assert out["error_code"] == "malformed_structured_output"


def test_analyze_accepts_structured_sdk_output(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("agent.runner.build_replenishment_agent", MagicMock())
    structured = ReplenishmentAgentDecision(
        recommendation_id="rec-1",
        store_id="ST001",
        sku="SKU-1001",
        product_name="Widget",
        forecast_units=10.0,
        usable_on_hand=1,
        in_transit=0,
        safety_stock=1,
        agent_recommended_quantity=12,
        risk="balanced",
        explanation="ok",
        next_action="review_recommendation",
        tools_used=["get_demand_forecast", "calculate_replenishment"],
    )
    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: SimpleNamespace(interruptions=[], final_output=structured),
    )
    out = analyze_replenishment("ST001", "SKU-1001", session_id="sess-1")
    assert out["status"] == "completed"
    assert out["recommendation_id"] == "rec-1"
    assert out["agent_recommended_quantity"] == 12


def test_answer_follow_up_uses_session_and_follow_up_workflow(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="t"
    )
    captured: dict = {}

    def _capture(agent, prompt, **kwargs):
        captured["session"] = kwargs.get("session")
        captured["run_config"] = kwargs.get("run_config")
        captured["context"] = kwargs.get("context")
        return SimpleNamespace(
            interruptions=[],
            final_output=FollowUpAnswer(
                recommendation_id=rec.recommendation_id,
                answer="Because the forecast and case pack require 12.",
                verified_facts=["agent_recommended_quantity=12"],
            ),
        )

    monkeypatch.setattr("agent.runner._execute_runner", _capture)
    monkeypatch.setattr("agent.runner.build_follow_up_agent", MagicMock())

    out = answer_follow_up(
        rec.recommendation_id,
        "Why 12?",
        user_id="alex.store",
        session_id="sess-z",
    )
    assert out["status"] == "completed"
    assert out["answer"].startswith("Because")
    assert captured["session"] is not None
    assert captured["session"].session_id == (
        f"replenishment:alex.store:{rec.recommendation_id}"
    )
    assert captured["run_config"].workflow_name == WORKFLOW_FOLLOW_UP
    assert captured["context"].conversation_id == follow_up_conversation_id(
        rec.recommendation_id, user_id="alex.store"
    )
    # Browser/UI session_id must not change conversational identity.
    assert "sess-z" not in captured["context"].conversation_id
    assert captured["context"].recommendation_id == rec.recommendation_id

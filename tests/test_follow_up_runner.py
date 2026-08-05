"""Checkpoint 7 — follow-up runner hardening (no live OpenAI calls)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agents import MaxTurnsExceeded, OutputGuardrailTripwireTriggered, ToolTimeoutError

from agent.orchestrator import follow_up_max_turns
from agent.runner import _execute_runner, answer_follow_up, follow_up_conversation_id
from agent.schemas import FollowUpAnswer
from agent.sessions import follow_up_session_id
from config import FOLLOW_UP_MAX_TURNS, WORKFLOW_FOLLOW_UP
from services import recommendation_service
from services.errors import AppError


def _make_rec(**kwargs):
    defaults = {
        "store_id": "ST001",
        "sku": "SKU-1001",
        "rationale": "follow-up-runner",
        "user_id": "alex.store",
    }
    defaults.update(kwargs)
    return recommendation_service.create_recommendation_record(**defaults)


def test_follow_up_max_turns_is_finite_and_bounded():
    turns = follow_up_max_turns()
    assert turns == FOLLOW_UP_MAX_TURNS
    assert 6 <= turns <= 8


def test_session_uses_user_id_and_recommendation_id(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec = _make_rec()
    captured: dict = {}

    def _capture(agent, prompt, **kwargs):
        captured["session"] = kwargs.get("session")
        captured["max_turns"] = kwargs.get("max_turns")
        captured["run_config"] = kwargs.get("run_config")
        return SimpleNamespace(
            interruptions=[],
            final_output=FollowUpAnswer(
                recommendation_id=rec.recommendation_id,
                question_type="explanation",
                answer="ok",
                verified_facts=["agent_recommended_quantity=1"],
            ),
        )

    monkeypatch.setattr("agent.runner._execute_runner", _capture)
    monkeypatch.setattr("agent.runner.build_follow_up_agent", MagicMock())

    out = answer_follow_up(
        rec.recommendation_id,
        "Summarize the recommendation context.",
        user_id="alex.store",
        session_id="browser-sess",
    )
    expected = follow_up_session_id("alex.store", rec.recommendation_id)
    assert captured["session"].session_id == expected
    assert out["follow_up_session_id"] == expected
    assert captured["max_turns"] == follow_up_max_turns()
    assert captured["run_config"].workflow_name == WORKFLOW_FOLLOW_UP
    meta = captured["run_config"].trace_metadata
    assert meta["workflow_name"] == WORKFLOW_FOLLOW_UP
    assert meta["user_id"] == "alex.store"
    assert meta["recommendation_id"] == rec.recommendation_id
    assert meta["question_type"]
    assert "browser-sess" not in expected


def test_missing_api_key_uses_deterministic_explanation_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    result = answer_follow_up(
        rec.recommendation_id,
        "Why is this quantity recommended?",
        user_id="alex.store",
    )
    assert result["status"] == "completed"
    assert result["mode"] == "deterministic_fallback"
    assert result["can_change_business_state"] is False
    assert any("agent_recommended_quantity=" in f for f in result["verified_facts"])
    assert (
        "api key" in result["answer"].lower()
        or "unavailable" in result["answer"].lower()
        or "verified" in result["answer"].lower()
    )
    # No invented quantity — must match stored recommendation.
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert str(stored["agent_recommended_quantity"]) in result["answer"]


def test_scenarios_work_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    proposed = max(rec.agent_recommended_quantity - 12, 0)
    qty = answer_follow_up(
        rec.recommendation_id,
        f"Why not order {proposed} units instead?",
        user_id="alex.store",
    )
    assert qty["mode"] == "scenario_service"
    assert qty["scenario_result"]["proposed_quantity"] == proposed

    delay = answer_follow_up(
        rec.recommendation_id,
        "What happens if the shipment is delayed by two days?",
        user_id="alex.store",
    )
    assert delay["mode"] == "scenario_service"
    assert delay["scenario_result"]["delay_days"] == 2


def test_missing_recommendation_controlled_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    result = answer_follow_up("REC-missing-runner", "Why?", user_id="alex.store")
    assert result["status"] == "error"
    assert result["error_code"] == "missing_recommendation"
    assert result["can_change_business_state"] is False


def test_empty_question_controlled_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = _make_rec()
    result = answer_follow_up(rec.recommendation_id, "   ", user_id="alex.store")
    assert result["status"] == "error"
    assert result["error_code"] == "empty_question"


@pytest.mark.parametrize(
    "exc,error_code",
    [
        (MaxTurnsExceeded("too many"), "max_turns_exceeded"),
        (ToolTimeoutError("get_recommendation", 30.0), "model_timeout"),
        (AppError("tool blew up", code="tool_error"), "tool_error"),
    ],
)
def test_follow_up_maps_runner_exceptions(monkeypatch, exc, error_code):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec = _make_rec()
    monkeypatch.setattr("agent.runner.build_follow_up_agent", MagicMock())
    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: (_ for _ in ()).throw(exc),
    )
    out = answer_follow_up(
        rec.recommendation_id,
        "Summarize the recommendation context.",
        user_id="alex.store",
    )
    assert out["status"] == "error"
    assert out["error_code"] == error_code
    assert out["can_change_business_state"] is False
    assert out["follow_up_session_id"] == follow_up_conversation_id(
        rec.recommendation_id, user_id="alex.store"
    )


def test_follow_up_maps_guardrail_tripwire(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec = _make_rec()
    monkeypatch.setattr("agent.runner.build_follow_up_agent", MagicMock())

    class _Trip(OutputGuardrailTripwireTriggered):
        def __init__(self) -> None:
            Exception.__init__(self, "tripwire")

    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: (_ for _ in ()).throw(_Trip()),
    )
    out = answer_follow_up(
        rec.recommendation_id,
        "Summarize the recommendation context.",
        user_id="alex.store",
    )
    assert out["error_code"] == "guardrail_tripwire"


def test_follow_up_maps_malformed_structured_output(monkeypatch):
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-test")
    rec = _make_rec()
    monkeypatch.setattr("agent.runner.build_follow_up_agent", MagicMock())
    monkeypatch.setattr(
        "agent.runner._execute_runner",
        lambda *_a, **_k: SimpleNamespace(
            interruptions=[],
            final_output={"not": "a FollowUpAnswer"},
        ),
    )
    out = answer_follow_up(
        rec.recommendation_id,
        "Summarize the recommendation context.",
        user_id="alex.store",
    )
    assert out["status"] == "error"
    assert out["error_code"] == "malformed_structured_output"


def test_execute_runner_avoids_run_sync_inside_async_loop_for_follow_up(monkeypatch):
    calls = {"run": 0, "run_sync": 0}

    async def _fake_run(*_a, **_k):
        calls["run"] += 1
        return SimpleNamespace(final_output={"ok": True})

    def _fake_run_sync(*_a, **_k):
        calls["run_sync"] += 1
        return SimpleNamespace(final_output={"ok": True})

    monkeypatch.setattr("agent.runner.Runner.run", _fake_run)
    monkeypatch.setattr("agent.runner.Runner.run_sync", _fake_run_sync)

    async def _inside():
        return _execute_runner(
            MagicMock(),
            "prompt",
            max_turns=follow_up_max_turns(),
            run_config=None,
            session=MagicMock(),
        )

    result = asyncio.run(_inside())
    assert result.final_output == {"ok": True}
    assert calls["run"] == 1
    assert calls["run_sync"] == 0

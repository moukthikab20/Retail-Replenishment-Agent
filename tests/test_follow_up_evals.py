"""Checkpoint 10 — follow-up evaluation dataset (structured outcomes, not prose)."""

from __future__ import annotations

import pytest

from tests.evals.follow_up_eval_runner import load_follow_up_cases, run_follow_up_case


REQUIRED_FOLLOW_UP_SCENARIOS = {
    "explain recommendation",
    "explain risk",
    "order less than recommendation",
    "order more than recommendation",
    "zero order quantity",
    "delayed shipment",
    "no shipment delay",
    "missing recommendation",
    "missing forecast data",
    "case-pack violation",
    "supplier maximum violation",
    "approve through chat",
    "order through chat",
    "change stored recommendation through chat",
    "follow-up context from previous question",
}


def test_follow_up_eval_dataset_has_required_scenarios():
    cases = load_follow_up_cases()
    assert len(cases) >= 15
    scenarios = {c["scenario"] for c in cases}
    missing = REQUIRED_FOLLOW_UP_SCENARIOS - scenarios
    assert not missing, f"Missing scenarios: {sorted(missing)}"
    for case in cases:
        assert "input" in case
        assert "question" in case["input"]
        assert "expected_tools" in case
        assert "prohibited_tools" in case
        assert "expected_question_type" in case
        assert "required_verified_facts" in case
        assert "expected_scenario_fields" in case or case.get("expected_scenario_fields") is None
        assert "expected_prohibition" in case or case.get("expected_prohibition") is None


@pytest.mark.parametrize("case_id", [c["id"] for c in load_follow_up_cases()])
def test_follow_up_eval_case_structured_outcomes(case_id, monkeypatch):
    case = next(c for c in load_follow_up_cases() if c["id"] == case_id)
    result = run_follow_up_case(case, monkeypatch)
    assert result.passed, f"{result.case_id}: {'; '.join(result.failures)}"


def test_follow_up_eval_does_not_score_prose_similarity(monkeypatch):
    """Scoring uses tools, question_type, facts, and scenario fields — not answer prose."""
    case = next(c for c in load_follow_up_cases() if c["id"] == "explain_recommendation")
    result = run_follow_up_case(case, monkeypatch)
    assert result.passed
    assert result.details.get("answer_ignored_for_scoring") is True
    payload = result.details["result"]
    assert "question_type" in payload
    assert "tools_used" in payload
    assert payload["can_change_business_state"] is False

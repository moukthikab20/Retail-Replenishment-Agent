"""Checkpoint 7 — evaluation dataset runner (structured outcomes)."""

from __future__ import annotations

import pytest

from tests.evals.eval_runner import load_cases, run_case


REQUIRED_SCENARIOS = {
    "normal stockout",
    "balanced inventory",
    "overstock",
    "zero sales",
    "insufficient history",
    "stale inventory",
    "in-transit stock",
    "open purchase order",
    "case-pack rounding",
    "minimum order quantity",
    "supplier maximum",
    "zero human proposal",
    "lower manual proposal",
    "higher manual proposal",
    "large override escalation",
    "unauthorized approval",
    "pending approval",
    "rejected approval",
    "duplicate order",
    "model/tool failure",
}


def test_eval_dataset_has_required_scenarios():
    cases = load_cases()
    assert len(cases) >= 20
    scenarios = {c["scenario"] for c in cases}
    missing = REQUIRED_SCENARIOS - scenarios
    assert not missing, f"Missing scenarios: {sorted(missing)}"
    for case in cases:
        assert "input" in case
        assert "expected_tools" in case
        assert "prohibited_tools" in case
        assert "expected_risk" in case or case["phase"] != "analysis"
        assert "expected_quantity" in case
        assert "expected_next_action" in case or case["phase"] != "analysis"
        assert "expected_approval_behavior" in case


@pytest.mark.parametrize("case_id", [c["id"] for c in load_cases()])
def test_eval_case_structured_outcomes(case_id, monkeypatch):
    case = next(c for c in load_cases() if c["id"] == case_id)
    result = run_case(case, monkeypatch)
    assert result.passed, f"{result.case_id}: {'; '.join(result.failures)}"


def test_eval_does_not_score_prose_similarity(monkeypatch):
    """Ensure analysis scoring uses structured fields, not explanation text."""
    case = next(c for c in load_cases() if c["id"] == "normal_stockout")
    result = run_case(case, monkeypatch)
    assert result.passed
    decision = result.details["decision"]
    assert "agent_recommended_quantity" in decision
    assert "risk" in decision
    assert "next_action" in decision
    assert "tools_used" in decision
    assert decision["agent_recommended_quantity"] == 72

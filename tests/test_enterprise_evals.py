"""Checkpoint 12 — enterprise replenishment evaluations (business outcomes)."""

from __future__ import annotations

import pytest

from tests.evals.enterprise_eval_runner import (
    REQUIRED_SCENARIOS,
    load_cases,
    run_case,
    validate_dataset,
)


def test_enterprise_dataset_contract():
    errors = validate_dataset()
    assert not errors, "; ".join(errors)
    cases = load_cases()
    assert len(cases) >= 25
    scenarios = {c["scenario"] for c in cases}
    assert REQUIRED_SCENARIOS <= scenarios


def test_enterprise_evals_do_not_score_prose():
    """Guardrail: cases assert structured business fields only."""
    for case in load_cases():
        assert "expected_answer_text" not in case
        assert "expected_similarity" not in case
        assert "bleu" not in case
        assert "rouge" not in case
        assert isinstance(case["expected_disposition"], str)
        assert "prohibited_actions" in case


@pytest.mark.parametrize("case_id", [c["id"] for c in load_cases()])
def test_enterprise_case_business_outcomes(case_id, monkeypatch):
    case = next(c for c in load_cases() if c["id"] == case_id)
    result = run_case(case, monkeypatch)
    assert result.passed, f"{result.case_id} ({result.scenario}): {'; '.join(result.failures)}"

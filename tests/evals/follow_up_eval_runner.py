"""Structured evaluation runner for follow-up cases.

Checks tool selection and structured FollowUpAnswer fields — not prose similarity.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.follow_up_guardrails import FOLLOW_UP_PROHIBITED_NEXT_ACTION
from agent.runner import answer_follow_up
from agent.sessions import follow_up_session_id, get_follow_up_session
from services import product_service, recommendation_service

CASES_PATH = Path(__file__).resolve().parent / "follow_up_cases.json"


@dataclass
class FollowUpCaseResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def load_follow_up_cases(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    return list(data["cases"])


def _apply_patches(monkeypatch: Any, case: dict[str, Any], recommendation_id: str) -> None:
    patches = list((case.get("input") or {}).get("patches") or [])
    if "missing_forecast" in patches:
        real_get = recommendation_service.get_recommendation

        def _no_forecast(rec_id: str, **kwargs: Any) -> dict[str, Any]:
            data = dict(real_get(rec_id, **kwargs))
            data["forecast_units"] = 0.0
            data["average_daily_sales"] = 0.0
            data["days_of_supply"] = None
            data["risk_level"] = "insufficient_data"
            return data

        monkeypatch.setattr(
            "services.scenario_service.recommendation_service.get_recommendation",
            _no_forecast,
        )
        monkeypatch.setattr(
            "agent.runner.recommendation_service.get_recommendation",
            _no_forecast,
        )

    if "supplier_maximum_36" in patches:
        real = product_service.get_product_details

        def _capped(sku: str):
            product = real(sku)
            return product.model_copy(
                update={
                    "minimum_order_quantity": 12,
                    "maximum_order_quantity": 36,
                    "case_pack": 12,
                }
            )

        monkeypatch.setattr(product_service, "get_product_details", _capped)
        monkeypatch.setattr(
            "services.scenario_service.product_service.get_product_details",
            _capped,
        )


def _tools_observed(result: dict[str, Any]) -> set[str]:
    tools = set(result.get("tools_used") or [])
    mode = result.get("mode")
    if mode == "scenario_service":
        scenario_type = result.get("scenario_type")
        if scenario_type == "quantity":
            tools.add("evaluate_quantity_scenario")
        elif scenario_type == "delay":
            tools.add("evaluate_delay_scenario")
    if mode == "deterministic_fallback":
        tools.add("get_recommendation")
    return tools


def _check_verified_facts(result: dict[str, Any], required: list[str]) -> list[str]:
    failures: list[str] = []
    facts = [str(f) for f in (result.get("verified_facts") or [])]
    joined = " | ".join(facts)
    for needle in required:
        if needle not in joined:
            failures.append(f"missing verified fact fragment: {needle!r}")
    return failures


def _check_scenario_fields(result: dict[str, Any], expected: dict[str, Any] | None) -> list[str]:
    if expected is None:
        return []
    failures: list[str] = []
    scenario = result.get("scenario_result") or {}
    for key, value in expected.items():
        if scenario.get(key) != value:
            failures.append(
                f"scenario_result[{key!r}] expected {value!r}, got {scenario.get(key)!r}"
            )
    return failures


def run_follow_up_case(case: dict[str, Any], monkeypatch: Any) -> FollowUpCaseResult:
    case_id = str(case["id"])
    failures: list[str] = []
    details: dict[str, Any] = {}
    case_input = case.get("input") or {}
    user_id = str(case_input.get("user_id") or "alex.store")
    question = str(case_input.get("question") or "")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")

    recommendation_id: str
    before: dict[str, Any] | None = None
    if case_input.get("create_recommendation"):
        rec = recommendation_service.create_recommendation_record(
            str(case_input.get("store_id") or "ST001"),
            str(case_input.get("sku") or "SKU-1001"),
            rationale=f"follow-up-eval:{case_id}",
            user_id=user_id,
        )
        recommendation_id = rec.recommendation_id
        before = recommendation_service.get_recommendation(recommendation_id)
    else:
        recommendation_id = str(case_input.get("recommendation_id") or "REC-eval-missing")

    _apply_patches(monkeypatch, case, recommendation_id)

    if case_input.get("seed_session"):
        session = get_follow_up_session(user_id, recommendation_id)
        prior = list(case_input.get("prior_messages") or [])
        if prior:
            asyncio.run(session.add_items(prior))
        details["seeded_items"] = len(prior)

    result = answer_follow_up(
        recommendation_id,
        question,
        user_id=user_id,
        session_id=f"eval-{case_id}",
        actor=user_id,
        actor_role="store_manager",
    )
    details["result"] = {
        "status": result.get("status"),
        "question_type": result.get("question_type"),
        "tools_used": result.get("tools_used"),
        "mode": result.get("mode"),
        "error_code": result.get("error_code"),
        "scenario_result": result.get("scenario_result"),
        "can_change_business_state": result.get("can_change_business_state"),
        "suggested_next_action": result.get("suggested_next_action"),
    }

    expected_status = case.get("expected_status")
    if expected_status and result.get("status") != expected_status:
        failures.append(
            f"status expected {expected_status!r}, got {result.get('status')!r}"
        )

    expected_qtype = case.get("expected_question_type")
    if expected_qtype and result.get("question_type") != expected_qtype:
        failures.append(
            f"question_type expected {expected_qtype!r}, got {result.get('question_type')!r}"
        )

    if case.get("expect_can_change_business_state") is False:
        if result.get("can_change_business_state") is not False:
            failures.append("can_change_business_state must be False")

    observed_tools = _tools_observed(result)
    for tool in case.get("expected_tools") or []:
        if tool not in observed_tools:
            failures.append(f"expected tool not observed: {tool}")
    for tool in case.get("prohibited_tools") or []:
        if tool in observed_tools:
            failures.append(f"prohibited tool was used: {tool}")

    failures.extend(
        _check_verified_facts(result, list(case.get("required_verified_facts") or []))
    )
    failures.extend(
        _check_scenario_fields(result, case.get("expected_scenario_fields"))
    )

    prohibition = case.get("expected_prohibition")
    if prohibition:
        if result.get("error_code") != prohibition.get("error_code"):
            failures.append(
                f"error_code expected {prohibition.get('error_code')!r}, "
                f"got {result.get('error_code')!r}"
            )
        expected_next = prohibition.get("suggested_next_action")
        if expected_next and result.get("suggested_next_action") != expected_next:
            failures.append(
                f"suggested_next_action expected {expected_next!r}, "
                f"got {result.get('suggested_next_action')!r}"
            )
        if result.get("question_type") == "prohibited_action":
            if result.get("suggested_next_action") != FOLLOW_UP_PROHIBITED_NEXT_ACTION:
                failures.append(
                    "prohibited answers must use Review/Formal Approval next action"
                )

    warning_needle = case.get("require_warning_contains")
    if warning_needle:
        scenario = result.get("scenario_result") or {}
        warnings = " ".join(str(w) for w in (scenario.get("warning_messages") or [])).lower()
        answer = str(result.get("answer") or "").lower()
        blob = warnings + " " + answer
        for needle in warning_needle:
            if needle.lower() not in blob:
                failures.append(f"expected warning/answer to mention {needle!r}")

    if case.get("expect_recommendation_unchanged") and before is not None:
        after = recommendation_service.get_recommendation(recommendation_id)
        if after["agent_recommended_quantity"] != before["agent_recommended_quantity"]:
            failures.append("agent_recommended_quantity changed during follow-up")
        if after["status"] != before["status"]:
            failures.append("recommendation status changed during follow-up")

    if case.get("expect_session_preserved"):
        expected_key = follow_up_session_id(user_id, recommendation_id)
        if result.get("follow_up_session_id") != expected_key:
            failures.append(
                f"follow_up_session_id expected {expected_key!r}, "
                f"got {result.get('follow_up_session_id')!r}"
            )
        session = get_follow_up_session(user_id, recommendation_id)
        items = asyncio.run(session.get_items())
        details["session_item_count"] = len(items)
        if len(items) < len(case_input.get("prior_messages") or []):
            failures.append("prior conversation memory was not preserved")

    # Never score prose similarity — answer text is ignored except optional warning needles.
    details["answer_ignored_for_scoring"] = True

    return FollowUpCaseResult(
        case_id=case_id,
        passed=not failures,
        failures=failures,
        details=details,
    )

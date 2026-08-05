"""Structured evaluation runner for replenishment agent cases.

Checks tool selection and structured outcomes — not prose similarity.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents import MaxTurnsExceeded

from agent.instructions import ANALYSIS_TOOL_SEQUENCE
from agent.runner import analyze_replenishment, resume_order_run, start_order_agent_after_approval
from config import AS_OF_DATE
from database.connection import get_session
from models.forecast import ForecastResult
from models.inventory import InventoryPosition
from models.product import Product
from repositories import purchase_order_repository
from services import (
    approval_service,
    human_review_service,
    product_service,
    purchase_order_service,
    recommendation_service,
)
from services.auth_service import AuthError

CASES_PATH = Path(__file__).resolve().parent / "replenishment_cases.json"


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    return list(data["cases"])


def _matches_quantity(actual: Any, expected: dict[str, Any] | None) -> bool:
    if expected is None:
        return True
    if "exact" in expected:
        exact = expected["exact"]
        if exact is None:
            return actual is None
        return actual == exact
    if actual is None:
        return False
    if "min" in expected and actual < expected["min"]:
        return False
    if "max" in expected and actual > expected["max"]:
        return False
    return True


def _matches_one(actual: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _apply_patches(monkeypatch: Any, case_input: dict[str, Any]) -> None:
    patches = list(case_input.get("patches") or [])
    store_id = case_input["store_id"]
    sku = case_input["sku"]

    if "stale_inventory" in patches:
        as_of = datetime.fromisoformat(AS_OF_DATE).replace(tzinfo=timezone.utc)
        base = recommendation_service.build_analysis(store_id, sku)["inventory"]
        stale = InventoryPosition(
            store_id=base.store_id,
            sku=base.sku,
            on_hand=base.on_hand,
            reserved=base.reserved,
            in_transit=base.in_transit,
            safety_stock=base.safety_stock,
            updated_at=as_of - timedelta(days=30),
            store_name=base.store_name,
        )
        monkeypatch.setattr(
            "services.inventory_service.get_inventory_position",
            lambda s, k: stale,
        )
        monkeypatch.setattr(
            "services.recommendation_service.inventory_service.get_inventory_position",
            lambda s, k: stale,
        )
        monkeypatch.setattr(
            "agent.runner.inventory_service.get_inventory_position",
            lambda s, k: stale,
        )

    if "zero_sales" in patches:
        zero = ForecastResult(
            store_id=store_id,
            sku=sku,
            forecast_units=0,
            average_daily_sales=0,
            forecast_days=7,
            method="trailing_average",
            generated_at=datetime.now(timezone.utc),
        )
        monkeypatch.setattr(
            "services.forecast_service.get_demand_forecast",
            lambda *a, **k: zero,
        )
        monkeypatch.setattr(
            "services.recommendation_service.forecast_service.get_demand_forecast",
            lambda *a, **k: zero,
        )

    if "insufficient_history" in patches:
        zero = ForecastResult(
            store_id=store_id,
            sku=sku,
            forecast_units=0,
            average_daily_sales=0,
            forecast_days=7,
            method="insufficient_data_zero",
            generated_at=datetime.now(timezone.utc),
        )
        empty_inv = InventoryPosition(
            store_id=store_id,
            sku=sku,
            on_hand=0,
            reserved=0,
            in_transit=0,
            safety_stock=product_service.get_product_details(sku).safety_stock_units,
            updated_at=datetime.now(timezone.utc),
        )
        monkeypatch.setattr(
            "services.forecast_service.get_demand_forecast",
            lambda *a, **k: zero,
        )
        monkeypatch.setattr(
            "services.recommendation_service.forecast_service.get_demand_forecast",
            lambda *a, **k: zero,
        )
        monkeypatch.setattr(
            "services.inventory_service.get_inventory_position",
            lambda s, k: empty_inv,
        )
        monkeypatch.setattr(
            "services.recommendation_service.inventory_service.get_inventory_position",
            lambda s, k: empty_inv,
        )
        monkeypatch.setattr(
            "agent.runner.inventory_service.get_inventory_position",
            lambda s, k: empty_inv,
        )

    if "force_overstock" in patches:
        base = recommendation_service.build_analysis(store_id, sku)["inventory"]
        fat = InventoryPosition(
            store_id=base.store_id,
            sku=base.sku,
            on_hand=500,
            reserved=0,
            in_transit=0,
            safety_stock=base.safety_stock,
            updated_at=datetime.now(timezone.utc),
            store_name=base.store_name,
        )
        monkeypatch.setattr(
            "services.inventory_service.get_inventory_position",
            lambda s, k: fat,
        )
        monkeypatch.setattr(
            "services.recommendation_service.inventory_service.get_inventory_position",
            lambda s, k: fat,
        )
        monkeypatch.setattr(
            "agent.runner.inventory_service.get_inventory_position",
            lambda s, k: fat,
        )

    if "force_moq" in patches:
        product = product_service.get_product_details(sku)
        patched = Product(
            sku=product.sku,
            product_name=product.product_name,
            unit_cost=product.unit_cost,
            case_pack=product.case_pack,
            minimum_order_quantity=24,
            maximum_order_quantity=product.maximum_order_quantity,
            safety_stock_units=product.safety_stock_units,
        )
        monkeypatch.setattr(
            "services.product_service.get_product_details",
            lambda s: patched,
        )
        monkeypatch.setattr(
            "services.recommendation_service.product_service.get_product_details",
            lambda s: patched,
        )

    if "force_max_order" in patches:
        product = product_service.get_product_details(sku)
        patched = Product(
            sku=product.sku,
            product_name=product.product_name,
            unit_cost=product.unit_cost,
            case_pack=product.case_pack,
            minimum_order_quantity=product.minimum_order_quantity,
            maximum_order_quantity=40,
            safety_stock_units=product.safety_stock_units,
        )
        monkeypatch.setattr(
            "services.product_service.get_product_details",
            lambda s: patched,
        )
        monkeypatch.setattr(
            "services.recommendation_service.product_service.get_product_details",
            lambda s: patched,
        )

    if "max_turns_exceeded" in patches:
        monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "sk-eval-test")
        monkeypatch.setattr("agent.runner.build_replenishment_agent", lambda *a, **k: object())
        monkeypatch.setattr(
            "agent.runner._execute_runner",
            lambda *a, **k: (_ for _ in ()).throw(MaxTurnsExceeded("eval max turns")),
        )


def _check_tools(
    decision: dict[str, Any],
    expected_tools: list[str],
    prohibited_tools: list[str],
    failures: list[str],
) -> None:
    used = set(decision.get("tools_used") or [])
    for tool in expected_tools:
        if tool not in used:
            failures.append(f"missing expected tool: {tool}")
    for tool in prohibited_tools:
        if tool in used:
            failures.append(f"prohibited tool was used: {tool}")


def _run_analysis_case(case: dict[str, Any], monkeypatch: Any) -> CaseResult:
    failures: list[str] = []
    case_input = case["input"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    if "max_turns_exceeded" not in (case_input.get("patches") or []):
        monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    _apply_patches(monkeypatch, case_input)

    decision = analyze_replenishment(
        case_input["store_id"],
        case_input["sku"],
        user_id="eval.user",
        session_id="eval-session",
    )

    behavior = case.get("expected_approval_behavior") or {}
    if behavior.get("analysis_error"):
        if decision.get("status") != "error":
            failures.append(f"expected analysis error, got status={decision.get('status')}")
        if decision.get("error_code") != behavior.get("error_code"):
            failures.append(
                f"error_code expected {behavior.get('error_code')}, got {decision.get('error_code')}"
            )
        if behavior.get("no_recommendation_id") and decision.get("recommendation_id"):
            failures.append("recommendation_id should be absent on analysis failure")
    else:
        if decision.get("status") != "completed":
            failures.append(f"analysis status expected completed, got {decision.get('status')}")
        _check_tools(
            decision,
            case.get("expected_tools") or [],
            case.get("prohibited_tools") or [],
            failures,
        )
        # Full analysis sequence should never invent tools outside contract when listed.
        if set(ANALYSIS_TOOL_SEQUENCE).issubset(case.get("expected_tools") or []):
            for tool in ANALYSIS_TOOL_SEQUENCE:
                if tool not in (decision.get("tools_used") or []):
                    failures.append(f"analysis sequence incomplete; missing {tool}")

    if not _matches_one(decision.get("risk"), case.get("expected_risk")):
        failures.append(
            f"risk expected {case.get('expected_risk')}, got {decision.get('risk')}"
        )
    if not _matches_one(decision.get("next_action"), case.get("expected_next_action")):
        failures.append(
            f"next_action expected {case.get('expected_next_action')}, "
            f"got {decision.get('next_action')}"
        )
    if not _matches_quantity(
        decision.get("agent_recommended_quantity"), case.get("expected_quantity")
    ):
        failures.append(
            f"quantity expected {case.get('expected_quantity')}, "
            f"got {decision.get('agent_recommended_quantity')}"
        )

    for key, value in (case.get("expected_fields") or {}).items():
        if decision.get(key) != value:
            failures.append(f"field {key} expected {value}, got {decision.get(key)}")

    for token in case.get("expected_constraints_contains") or []:
        constraints = decision.get("constraints_applied") or []
        if token not in constraints:
            failures.append(f"constraints missing {token}; got {constraints}")

    return CaseResult(
        case_id=case["id"],
        passed=not failures,
        failures=failures,
        details={"decision": decision},
    )


def _create_recommendation(case_input: dict[str, Any]) -> dict[str, Any]:
    decision = analyze_replenishment(
        case_input["store_id"],
        case_input["sku"],
        user_id="eval.user",
        session_id="eval-session",
    )
    return decision


def _run_review_case(case: dict[str, Any], monkeypatch: Any) -> CaseResult:
    failures: list[str] = []
    case_input = case["input"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = _create_recommendation(case_input)
    if decision.get("status") != "completed":
        return CaseResult(case["id"], False, ["failed to create recommendation for review case"])

    if not _matches_quantity(
        decision.get("agent_recommended_quantity"), case.get("expected_quantity")
    ):
        failures.append(
            f"agent qty expected {case.get('expected_quantity')}, "
            f"got {decision.get('agent_recommended_quantity')}"
        )

    preview = human_review_service.preview_human_review(
        recommendation_id=decision["recommendation_id"],
        choice=case_input["choice"],
        human_proposed_quantity=case_input.get("human_proposed_quantity"),
        override_reason=case_input.get("override_reason"),
    )
    behavior = case.get("expected_approval_behavior") or {}
    if behavior.get("review_valid") and not preview.get("valid"):
        failures.append(f"review expected valid, messages={preview.get('validation_messages')}")
    if "human_proposed_quantity" in behavior:
        if preview.get("human_proposed_quantity") != behavior["human_proposed_quantity"]:
            failures.append(
                f"human qty expected {behavior['human_proposed_quantity']}, "
                f"got {preview.get('human_proposed_quantity')}"
            )
    if behavior.get("agent_recommended_quantity_unchanged"):
        if preview.get("agent_recommended_quantity") != decision["agent_recommended_quantity"]:
            failures.append("agent_recommended_quantity was altered during review preview")
    if "override_used" in behavior and preview.get("override_used") != behavior["override_used"]:
        failures.append(
            f"override_used expected {behavior['override_used']}, got {preview.get('override_used')}"
        )
    if "requires_escalation" in behavior and preview.get("requires_escalation") != behavior[
        "requires_escalation"
    ]:
        failures.append(
            f"requires_escalation expected {behavior['requires_escalation']}, "
            f"got {preview.get('requires_escalation')}"
        )

    review = human_review_service.submit_human_review(
        recommendation_id=decision["recommendation_id"],
        choice=case_input["choice"],
        human_proposed_quantity=case_input.get("human_proposed_quantity"),
        override_reason=case_input.get("override_reason"),
        submitted_by="eval.submitter",
        actor_role=case_input.get("submitter_role", "inventory_planner"),
        user_id="eval.submitter",
        session_id="eval-session",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor="eval.submitter",
        actor_role=case_input.get("submitter_role", "inventory_planner"),
    )
    if "required_role" in behavior and approval.required_role != behavior["required_role"]:
        failures.append(
            f"required_role expected {behavior['required_role']}, got {approval.required_role}"
        )
    if review.agent_recommended_quantity != decision["agent_recommended_quantity"]:
        failures.append("stored review overwrote agent_recommended_quantity")

    return CaseResult(case["id"], not failures, failures, {"preview": preview, "approval": approval.model_dump(mode="json")})


def _run_approval_case(case: dict[str, Any], monkeypatch: Any) -> CaseResult:
    failures: list[str] = []
    case_input = case["input"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = _create_recommendation(case_input)
    review = human_review_service.submit_human_review(
        recommendation_id=decision["recommendation_id"],
        choice=case_input.get("choice", "use_agent"),
        human_proposed_quantity=case_input.get("human_proposed_quantity"),
        override_reason=case_input.get("override_reason"),
        submitted_by="eval.submitter",
        actor_role=case_input.get("submitter_role", "store_manager"),
        user_id="eval.submitter",
        session_id="eval-session",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor="eval.submitter",
        actor_role=case_input.get("submitter_role", "store_manager"),
    )
    behavior = case.get("expected_approval_behavior") or {}

    if case_input.get("stop_after") == "request_approval":
        status = approval_service.get_approval_status(approval.approval_id)
        if status.get("status") != "pending":
            failures.append(f"expected pending approval, got {status.get('status')}")
        if behavior.get("can_create_po") is False:
            try:
                purchase_order_service.create_mock_purchase_order(approval.approval_id)
                failures.append("PO creation should fail while approval is pending")
            except Exception:
                pass
        return CaseResult(case["id"], not failures, failures, {"approval": status})

    decision_value = case_input.get("approval_decision", "approve")
    try:
        decided = approval_service.decide_approval(
            approval_id=approval.approval_id,
            decision=decision_value,
            actor="eval.approver",
            actor_role=case_input.get("approver_role", "store_manager"),
            rejection_reason="Eval reject" if decision_value == "reject" else None,
        )
        if behavior.get("approval_status") == "unauthorized":
            failures.append("expected unauthorized approval to fail")
        elif decided.status != behavior.get("approval_status", decided.status):
            failures.append(
                f"approval_status expected {behavior.get('approval_status')}, got {decided.status}"
            )
        if behavior.get("can_create_po") is False and decided.status != "approved":
            try:
                purchase_order_service.create_mock_purchase_order(decided.approval_id)
                failures.append("PO creation should fail for non-approved status")
            except Exception:
                pass
    except (AuthError, PermissionError, ValueError) as exc:
        if behavior.get("approval_status") != "unauthorized":
            failures.append(f"unexpected approval error: {exc}")
        else:
            text = str(exc).lower()
            needle = (behavior.get("error_contains") or "not authorized").lower()
            if needle not in text and "authoriz" not in text and "permission" not in text:
                failures.append(f"unauthorized error text mismatch: {exc}")

    return CaseResult(case["id"], not failures, failures, {})


def _run_order_case(case: dict[str, Any], monkeypatch: Any) -> CaseResult:
    failures: list[str] = []
    case_input = case["input"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    decision = _create_recommendation(case_input)
    review = human_review_service.submit_human_review(
        recommendation_id=decision["recommendation_id"],
        choice=case_input.get("choice", "use_agent"),
        human_proposed_quantity=case_input.get("human_proposed_quantity"),
        override_reason=case_input.get("override_reason"),
        submitted_by="eval.submitter",
        actor_role=case_input.get("submitter_role", "store_manager"),
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)
    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="eval.approver",
        actor_role=case_input.get("approver_role", "store_manager"),
    )
    paused = start_order_agent_after_approval(
        approval_id=decided.approval_id,
        recommendation_id=decision["recommendation_id"],
        actor="eval.hitl",
        actor_role=case_input.get("hitl_actor_role", "category_manager"),
    )
    if paused.get("status") != "paused":
        failures.append(f"expected HITL pause, got {paused.get('status')}")
    resumed = resume_order_run(
        run_id=paused["run_id"],
        approve=True,
        actor="eval.hitl",
        actor_role=case_input.get("hitl_actor_role", "category_manager"),
    )
    behavior = case.get("expected_approval_behavior") or {}
    if behavior.get("order_created") and resumed.get("status") != "completed":
        failures.append(f"expected order completed, got {resumed.get('status')}")
    po = resumed.get("purchase_order") or {}
    if behavior.get("quantities_separate"):
        if po.get("agent_recommended_quantity") != decision["agent_recommended_quantity"]:
            failures.append("PO agent quantity mismatch")
        if po.get("human_proposed_quantity") != review.human_proposed_quantity:
            failures.append("PO human quantity mismatch")
        if po.get("approved_final_quantity") != decided.approved_final_quantity:
            failures.append("PO approved quantity mismatch")
    if behavior.get("duplicate_resume_same_po"):
        again = resume_order_run(
            run_id=paused["run_id"],
            approve=True,
            actor="eval.hitl2",
            actor_role="administrator",
        )
        if again.get("purchase_order", {}).get("purchase_order_id") != po.get("purchase_order_id"):
            failures.append("duplicate resume created a different PO")
        with get_session() as session:
            existing = purchase_order_repository.get_purchase_order_by_approval(
                session, decided.approval_id
            )
        if existing is None:
            failures.append("PO missing after duplicate resume")

    return CaseResult(case["id"], not failures, failures, {"po": po})


def run_case(case: dict[str, Any], monkeypatch: Any) -> CaseResult:
    phase = case.get("phase", "analysis")
    case = deepcopy(case)
    if phase == "analysis":
        return _run_analysis_case(case, monkeypatch)
    if phase == "review":
        return _run_review_case(case, monkeypatch)
    if phase == "approval":
        return _run_approval_case(case, monkeypatch)
    if phase == "order":
        return _run_order_case(case, monkeypatch)
    return CaseResult(case["id"], False, [f"unknown phase: {phase}"])


def run_all_cases(monkeypatch: Any, path: Path | None = None) -> list[CaseResult]:
    return [run_case(case, monkeypatch) for case in load_cases(path)]

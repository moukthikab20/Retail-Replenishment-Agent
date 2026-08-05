"""Checkpoint 4 — deterministic quantity scenario service and tool."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agent.context import ReplenishmentRunContext
from agent.tools import FOLLOW_UP_TOOLS, evaluate_quantity_scenario
from agents.tool_context import ToolContext
from config import ESCALATION_REQUIRED_PERCENT, ESCALATION_WARNING_PERCENT
from services import product_service, recommendation_service, scenario_service
from services.errors import AppError


def _make_rec(**kwargs):
    defaults = {
        "store_id": "ST001",
        "sku": "SKU-1001",
        "rationale": "quantity-scenario",
    }
    defaults.update(kwargs)
    return recommendation_service.create_recommendation_record(**defaults)


def _invoke_tool(payload: dict[str, Any]) -> Any:
    args_json = json.dumps(payload)

    async def _run() -> Any:
        ctx = ToolContext(
            context=ReplenishmentRunContext(run_id="RUN-qty-scenario", actor="tester"),
            tool_name=evaluate_quantity_scenario.name,
            tool_call_id="call-qty",
            tool_arguments=args_json,
        )
        return await evaluate_quantity_scenario.on_invoke_tool(ctx, args_json)

    return asyncio.run(_run())


def test_quantity_scenario_tool_registered_for_follow_up():
    assert "evaluate_quantity_scenario" in {t.name for t in FOLLOW_UP_TOOLS}


def test_same_quantity_scenario():
    rec = _make_rec()
    qty = rec.agent_recommended_quantity
    result = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, qty)
    assert result["hypothetical"] is True
    assert result["proposed_quantity"] == qty
    assert result["agent_recommended_quantity"] == qty
    assert result["difference_units"] == 0
    assert result["difference_percent"] == 0.0
    assert result["case_pack_compliant"] is True
    assert result["requires_escalation"] is False
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == qty


def test_lower_and_higher_quantity_scenarios():
    rec = _make_rec()
    agent_qty = rec.agent_recommended_quantity
    lower = max(agent_qty - 12, 0)
    higher = agent_qty + 12

    low = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, lower)
    high = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, higher)

    assert low["difference_units"] == lower - agent_qty
    assert high["difference_units"] == higher - agent_qty
    assert low["difference_percent"] >= 0
    assert high["difference_percent"] >= 0
    assert low["projected_inventory"] < high["projected_inventory"]


def test_zero_quantity_requires_escalation():
    rec = _make_rec()
    result = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, 0)
    assert result["proposed_quantity"] == 0
    assert result["requires_escalation"] is True
    assert result["requires_warning"] is True
    assert any("zero" in m.lower() for m in result["warning_messages"])


def test_negative_quantity_rejected():
    rec = _make_rec()
    with pytest.raises(AppError) as exc:
        scenario_service.evaluate_quantity_scenario(rec.recommendation_id, -1)
    assert exc.value.code == "domain_error"


def test_non_integer_quantity_rejected():
    rec = _make_rec()
    with pytest.raises(AppError) as exc:
        scenario_service.evaluate_quantity_scenario(rec.recommendation_id, True)  # type: ignore[arg-type]
    assert "whole number" in str(exc.value).lower()


def test_case_pack_compliant_and_noncompliant():
    rec = _make_rec()
    product = product_service.get_product_details("SKU-1001")
    case_pack = product.case_pack
    compliant_qty = case_pack * 2
    noncompliant_qty = case_pack * 2 + 1

    ok = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, compliant_qty)
    bad = scenario_service.evaluate_quantity_scenario(
        rec.recommendation_id, noncompliant_qty
    )

    assert ok["case_pack_compliant"] is True
    assert bad["case_pack_compliant"] is False
    assert bad["nearest_lower_valid_quantity"] == compliant_qty
    assert bad["nearest_higher_valid_quantity"] == case_pack * 3
    assert any("not a multiple" in m.lower() for m in bad["warning_messages"])
    # Must not silently round proposed quantity.
    assert bad["proposed_quantity"] == noncompliant_qty


def test_minimum_and_maximum_order_violations(monkeypatch):
    rec = _make_rec()
    real = product_service.get_product_details

    def _constrained(sku: str):
        product = real(sku)
        return product.model_copy(
            update={
                "minimum_order_quantity": 24,
                "maximum_order_quantity": 36,
                "case_pack": 12,
            }
        )

    monkeypatch.setattr(product_service, "get_product_details", _constrained)
    monkeypatch.setattr(
        "services.scenario_service.product_service.get_product_details", _constrained
    )

    below_min = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, 12)
    assert below_min["minimum_order_compliant"] is False
    assert below_min["requires_warning"] is True
    assert any("minimum" in m.lower() for m in below_min["warning_messages"])

    above_max = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, 48)
    assert above_max["maximum_order_compliant"] is False
    assert above_max["proposed_quantity"] == 48  # not clamped
    assert any("maximum" in m.lower() for m in above_max["warning_messages"])


def test_warning_and_escalation_thresholds():
    rec = _make_rec()
    agent_qty = max(rec.agent_recommended_quantity, 100)

    # Force a known agent qty by patching get_recommendation return fields via new rec
    # Use percent math against the actual agent recommendation.
    agent = rec.agent_recommended_quantity
    if agent <= 0:
        pytest.skip("need positive agent quantity for percent thresholds")

    warn_delta = int((float(ESCALATION_WARNING_PERCENT) / 100.0) * agent) + 1
    esc_delta = int((float(ESCALATION_REQUIRED_PERCENT) / 100.0) * agent) + 1
    warn_qty = agent + warn_delta
    esc_qty = agent + esc_delta

    # Align to case pack only for the threshold assertion path when possible;
    # compliance is independent of warning math.
    warn = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, warn_qty)
    esc = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, esc_qty)

    assert warn["difference_percent"] > float(ESCALATION_WARNING_PERCENT)
    assert warn["requires_warning"] is True
    assert esc["difference_percent"] > float(ESCALATION_REQUIRED_PERCENT)
    assert esc["requires_escalation"] is True
    assert any("escalation" in m.lower() for m in esc["warning_messages"])


def test_projected_stockout_and_overstock_risks(monkeypatch):
    rec = _make_rec()

    def _stockout(**_kwargs):
        return {
            "risk_level": "stockout",
            "reasons": ["forced stockout"],
            "projected_days_of_supply": 1.0,
        }

    def _overstock(**_kwargs):
        return {
            "risk_level": "overstock",
            "reasons": ["forced overstock"],
            "projected_days_of_supply": 40.0,
        }

    monkeypatch.setattr(
        "services.scenario_service.risk_service.project_risk_after_order",
        _stockout,
    )
    stockout = scenario_service.evaluate_quantity_scenario(rec.recommendation_id, 0)
    assert stockout["projected_risk"] == "stockout"

    monkeypatch.setattr(
        "services.scenario_service.risk_service.project_risk_after_order",
        _overstock,
    )
    overstock = scenario_service.evaluate_quantity_scenario(
        rec.recommendation_id, rec.agent_recommended_quantity + 120
    )
    assert overstock["projected_risk"] == "overstock"


def test_scenario_does_not_create_human_review(monkeypatch):
    rec = _make_rec()
    called = {"submit": False}

    def _boom(*_a, **_k):
        called["submit"] = True
        raise AssertionError("must not submit human review")

    monkeypatch.setattr(
        "services.human_review_service.submit_human_review",
        _boom,
    )
    result = scenario_service.evaluate_quantity_scenario(
        rec.recommendation_id, max(rec.agent_recommended_quantity - 12, 0)
    )
    assert result["hypothetical"] is True
    assert called["submit"] is False
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_evaluate_quantity_scenario_tool_returns_structured_fields():
    rec = _make_rec()
    proposed = max(rec.agent_recommended_quantity - 12, 0)
    result = _invoke_tool(
        {
            "recommendation_id": rec.recommendation_id,
            "proposed_quantity": proposed,
        }
    )
    assert isinstance(result, dict)
    for key in (
        "recommendation_id",
        "agent_recommended_quantity",
        "proposed_quantity",
        "difference_units",
        "difference_percent",
        "projected_inventory",
        "projected_days_of_supply",
        "projected_risk",
        "case_pack_compliant",
        "nearest_lower_valid_quantity",
        "nearest_higher_valid_quantity",
        "minimum_order_compliant",
        "maximum_order_compliant",
        "requires_warning",
        "requires_escalation",
        "warning_messages",
    ):
        assert key in result
    json.dumps(result)

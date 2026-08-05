"""Checkpoint 5 — deterministic shipment delay scenario service and tool."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agent.context import ReplenishmentRunContext
from agent.tools import FOLLOW_UP_TOOLS, evaluate_delay_scenario
from agents.tool_context import ToolContext
from services import recommendation_service, scenario_service
from services.errors import AppError


def _make_rec(**kwargs):
    defaults = {
        "store_id": "ST001",
        "sku": "SKU-1001",
        "rationale": "delay-scenario",
    }
    defaults.update(kwargs)
    return recommendation_service.create_recommendation_record(**defaults)


def _patch_recommendation(monkeypatch, **overrides):
    real_get = recommendation_service.get_recommendation

    def _patched(recommendation_id: str, **kwargs):
        base = dict(real_get(recommendation_id, **kwargs))
        base.update(overrides)
        return base

    monkeypatch.setattr(
        "services.scenario_service.recommendation_service.get_recommendation",
        _patched,
    )


def _invoke_tool(payload: dict[str, Any]) -> Any:
    args_json = json.dumps(payload)

    async def _run() -> Any:
        ctx = ToolContext(
            context=ReplenishmentRunContext(run_id="RUN-delay-scenario", actor="tester"),
            tool_name=evaluate_delay_scenario.name,
            tool_call_id="call-delay",
            tool_arguments=args_json,
        )
        return await evaluate_delay_scenario.on_invoke_tool(ctx, args_json)

    return asyncio.run(_run())


def test_delay_scenario_tool_registered_for_follow_up():
    assert "evaluate_delay_scenario" in {t.name for t in FOLLOW_UP_TOOLS}


def test_zero_delay_scenario():
    rec = _make_rec()
    result = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 0)
    assert result["hypothetical"] is True
    assert result["delay_days"] == 0
    assert result["stockout_before_arrival"] is False
    assert result["expected_shortfall_units"] == 0
    assert result["additional_quantity_suggested"] == 0
    assert "original_days_of_supply" in result
    assert "revised_days_of_supply" in result
    assert result["original_risk"]
    assert result["revised_risk"]
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_one_day_and_multi_day_delay():
    rec = _make_rec()
    one = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 1)
    multi = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 5)
    assert one["delay_days"] == 1
    assert multi["delay_days"] == 5
    assert multi["demand_during_delay"] >= one["demand_during_delay"]
    assert multi["projected_on_hand_at_arrival"] <= one["projected_on_hand_at_arrival"]


def test_no_stockout_before_arrival(monkeypatch):
    rec = _make_rec()
    _patch_recommendation(
        monkeypatch,
        usable_on_hand=10_000,
        in_transit=100,
        average_daily_sales=10.0,
        forecast_units=70.0,
        days_of_supply=100.0,
        risk_level="balanced",
    )
    result = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 2)
    assert result["stockout_before_arrival"] is False
    assert result["expected_shortfall_units"] == 0
    assert result["additional_quantity_suggested"] == 0


def test_stockout_before_arrival(monkeypatch):
    rec = _make_rec()
    _patch_recommendation(
        monkeypatch,
        usable_on_hand=5,
        in_transit=48,
        average_daily_sales=10.0,
        forecast_units=70.0,
        days_of_supply=0.5,
        risk_level="stockout",
        agent_recommended_quantity=24,
    )
    result = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 3)
    assert result["stockout_before_arrival"] is True
    assert result["expected_shortfall_units"] > 0
    assert result["additional_quantity_suggested"] >= 1
    assert any("stockout" in m.lower() for m in result["warning_messages"])


def test_missing_forecast_reported(monkeypatch):
    rec = _make_rec()
    _patch_recommendation(
        monkeypatch,
        usable_on_hand=20,
        in_transit=12,
        average_daily_sales=0.0,
        forecast_units=0.0,
        days_of_supply=None,
        risk_level="insufficient_data",
    )
    result = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 2)
    assert result["revised_days_of_supply"] is None
    assert any("forecast" in m.lower() for m in result["warning_messages"])
    assert result["hypothetical"] is True


def test_missing_recommendation_rejected():
    with pytest.raises(Exception) as exc:
        scenario_service.evaluate_delay_scenario("REC-missing-delay", 2)
    text = str(exc.value).lower()
    assert "not found" in text or "recommendation" in text


def test_negative_delay_rejected():
    rec = _make_rec()
    with pytest.raises(AppError) as exc:
        scenario_service.evaluate_delay_scenario(rec.recommendation_id, -1)
    assert exc.value.code == "domain_error"


def test_non_integer_delay_rejected():
    rec = _make_rec()
    with pytest.raises(AppError) as exc:
        scenario_service.evaluate_delay_scenario(rec.recommendation_id, True)  # type: ignore[arg-type]
    assert "integer" in str(exc.value).lower()


def test_delay_does_not_mutate_recommendation_or_create_review(monkeypatch):
    rec = _make_rec()
    called = {"submit": False}

    def _boom(*_a, **_k):
        called["submit"] = True
        raise AssertionError("must not submit human review")

    monkeypatch.setattr("services.human_review_service.submit_human_review", _boom)
    result = scenario_service.evaluate_delay_scenario(rec.recommendation_id, 2)
    assert result["hypothetical"] is True
    assert called["submit"] is False
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_evaluate_delay_scenario_tool_returns_structured_fields():
    rec = _make_rec()
    result = _invoke_tool(
        {"recommendation_id": rec.recommendation_id, "delay_days": 2}
    )
    assert isinstance(result, dict)
    for key in (
        "recommendation_id",
        "delay_days",
        "original_days_of_supply",
        "revised_days_of_supply",
        "original_risk",
        "revised_risk",
        "expected_shortfall_units",
        "stockout_before_arrival",
        "additional_quantity_suggested",
        "warning_messages",
    ):
        assert key in result
    json.dumps(result)

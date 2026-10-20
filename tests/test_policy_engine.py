"""Checkpoint 2 — deterministic policy / guardrail engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from models.policy import PolicyConfig
from services import policy_service, recommendation_service
from services.recommendation_service import build_analysis


def _policy(**overrides) -> PolicyConfig:
    base = policy_service.default_policy_config(policy_version="test-v1")
    return base.model_copy(update=overrides)


def _eval(store_id="ST001", sku="SKU-1002", policy=None, **kwargs):
    analysis = build_analysis(store_id, sku)
    return policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        policy=policy or _policy(),
        confidence=kwargs.pop("confidence", Decimal("0.95")),
        history_days=kwargs.pop("history_days", 30),
        order_value=kwargs.pop("order_value", Decimal("100")),
        promotion_overlap=kwargs.pop("promotion_overlap", False),
        **kwargs,
    )


def _rule(result, name: str):
    return next(r for r in result.evaluated_rules if r.rule_name == name)


def test_ensure_default_policy_persisted():
    policy = policy_service.ensure_default_policy(created_by="test")
    loaded = policy_service.get_active_policy()
    assert loaded.policy_id == policy.policy_id
    assert loaded.active is True
    assert loaded.auto_release_max_value > 0


def test_rule_inventory_freshness_blocks():
    analysis = build_analysis("ST001", "SKU-1002")
    stale = analysis["inventory"].model_copy(
        update={"updated_at": datetime.now(timezone.utc) - timedelta(hours=500)}
    )
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=stale,
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        policy=_policy(maximum_inventory_age_hours=48),
        confidence=0.95,
        history_days=30,
        order_value=100,
        as_of=datetime.now(timezone.utc),
    )
    assert result.disposition == "blocked"
    assert "inventory_freshness" in result.failed_rules
    rule = _rule(result, "inventory_freshness")
    assert rule.result == "fail"
    assert rule.action == "blocked"
    assert rule.observed_value > 48


def test_rule_minimum_confidence_requires_review():
    result = _eval(confidence=Decimal("0.40"))
    assert result.disposition == "human_review"
    assert "minimum_confidence" in result.failed_rules
    rule = _rule(result, "minimum_confidence")
    assert rule.observed_value == 0.4
    assert rule.threshold == 0.75
    assert rule.action == "human_review"


def test_rule_stockout_requires_review():
    result = _eval(sku="SKU-1001", confidence=0.95, order_value=100)
    assert result.disposition == "human_review"
    assert "stockout_review" in result.failed_rules
    rule = _rule(result, "stockout_review")
    assert rule.observed_value == "stockout"
    assert rule.action == "human_review"


def test_rule_stockout_review_can_be_disabled():
    result = _eval(
        sku="SKU-1001",
        policy=_policy(require_review_for_stockout=False),
        confidence=0.95,
        order_value=50,
    )
    assert "stockout_review" not in result.failed_rules
    assert result.disposition == "auto_release"


def test_rule_overstock_max_dos_no_order():
    analysis = build_analysis("ST001", "SKU-1002")
    replenishment = analysis["replenishment"].model_copy(
        update={
            "recommended_quantity": 0,
            "days_of_supply": Decimal("30"),
        }
    )
    risk = {
        "risk_level": "overstock",
        "reasons": ["high DOS"],
        "projected_days_of_supply": 30.0,
    }
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=replenishment,
        risk=risk,
        policy=_policy(maximum_days_of_supply=Decimal("14")),
        confidence=0.95,
        history_days=30,
        order_value=0,
    )
    assert result.disposition == "no_order"
    assert "maximum_days_of_supply" in result.failed_rules or "zero_quantity" in result.failed_rules
    dos_rule = _rule(result, "maximum_days_of_supply")
    assert dos_rule.action == "no_order"


def test_rule_overstock_with_positive_qty_requires_review():
    analysis = build_analysis("ST001", "SKU-1002")
    replenishment = analysis["replenishment"].model_copy(
        update={
            "recommended_quantity": 24,
            "days_of_supply": Decimal("30"),
        }
    )
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=replenishment,
        risk={"risk_level": "overstock", "reasons": ["high DOS"]},
        policy=_policy(require_review_for_overstock=True),
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    assert result.disposition == "human_review"
    assert _rule(result, "maximum_days_of_supply").action == "human_review"


def test_rule_order_value_ceiling():
    result = _eval(order_value=Decimal("3000"), confidence=0.95)
    assert result.disposition == "human_review"
    assert "auto_release_max_value" in result.failed_rules
    rule = _rule(result, "auto_release_max_value")
    assert rule.observed_value == 3000.0
    assert rule.threshold == 2500.0


def test_rule_missing_critical_data_blocks():
    analysis = build_analysis("ST001", "SKU-1002")
    result = policy_service.evaluate_replenishment_policy(
        product=None,
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        policy=_policy(),
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    assert result.disposition == "blocked"
    assert "missing_critical_data" in result.failed_rules


def test_rule_insufficient_data_risk_blocks():
    analysis = build_analysis("ST001", "SKU-1002")
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk={"risk_level": "insufficient_data", "reasons": ["no sales"]},
        policy=_policy(),
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    assert result.disposition == "blocked"
    assert "missing_critical_data" in result.failed_rules


def test_rule_minimum_history_blocks():
    result = _eval(history_days=2, confidence=0.95)
    assert result.disposition == "blocked"
    assert "minimum_history" in result.failed_rules


def test_rule_promotion_overlap_requires_review():
    result = _eval(promotion_overlap=True, confidence=0.95, order_value=100)
    assert result.disposition == "human_review"
    assert "promotion_overlap" in result.failed_rules


def test_rule_formal_approval_value_flags_review():
    result = _eval(order_value=Decimal("6000"), confidence=0.95)
    assert result.disposition == "human_review"
    assert "formal_approval_value" in result.failed_rules
    assert result.warnings


def test_auto_release_when_all_rules_pass():
    result = _eval(sku="SKU-1002", confidence=0.95, history_days=30, order_value=100)
    assert result.disposition == "auto_release"
    assert result.passed is True
    assert result.failed_rules == []
    assert all(r.result in {"pass", "skip"} for r in result.evaluated_rules)


def test_zero_quantity_is_no_order():
    analysis = build_analysis("ST001", "SKU-1002")
    replenishment = analysis["replenishment"].model_copy(
        update={"recommended_quantity": 0, "days_of_supply": Decimal("5")}
    )
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=replenishment,
        risk={"risk_level": "balanced", "reasons": []},
        policy=_policy(),
        confidence=0.95,
        history_days=30,
        order_value=0,
    )
    assert result.disposition == "no_order"
    assert "zero_quantity" in result.failed_rules


def test_combination_stale_beats_review():
    analysis = build_analysis("ST001", "SKU-1001")
    stale = analysis["inventory"].model_copy(
        update={"updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}
    )
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=stale,
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        policy=_policy(maximum_inventory_age_hours=24),
        confidence=0.2,
        history_days=30,
        order_value=9000,
        as_of=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    assert result.disposition == "blocked"
    assert "inventory_freshness" in result.failed_rules


def test_combination_low_confidence_and_high_value():
    result = _eval(confidence=0.5, order_value=3000)
    assert result.disposition == "human_review"
    assert "minimum_confidence" in result.failed_rules
    assert "auto_release_max_value" in result.failed_rules


def test_policy_evaluation_persisted_on_recommendation():
    analysis = build_analysis("ST001", "SKU-1002")
    evaluation = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        policy=policy_service.ensure_default_policy(),
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1002",
        rationale="policy persist test",
        enforce_rate_limit=False,
        disposition=evaluation.disposition,
        status=evaluation.recommendation_status,
        policy_result=evaluation.model_dump(mode="json"),
    )
    loaded = recommendation_service.get_recommendation(rec.recommendation_id)
    assert loaded["disposition"] == "auto_release"
    assert loaded["policy_version"]
    assert loaded["policy_evaluation"]["evaluated_rules"]
    assert isinstance(loaded["policy_evaluation"]["evaluated_rules"], list)
    assert len(loaded["policy_evaluation"]["evaluated_rules"]) >= 8
    names = {r["rule_name"] for r in loaded["policy_evaluation"]["evaluated_rules"]}
    assert "inventory_freshness" in names
    assert "minimum_confidence" in names
    assert "auto_release_max_value" in names


def test_example_dispositions_a_b_c_d():
    """SKU A auto_release, B human_review, C blocked, D no_order."""
    policy = _policy()

    # A — balanced / within every gate
    a = _eval(sku="SKU-1002", policy=policy, confidence=0.95, order_value=100)
    assert a.disposition == "auto_release"

    # B — stockout exception
    b = _eval(sku="SKU-1001", policy=policy, confidence=0.95, order_value=100)
    assert b.disposition == "human_review"

    # C — stale inventory
    analysis_c = build_analysis("ST001", "SKU-1003")
    stale = analysis_c["inventory"].model_copy(
        update={"updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}
    )
    c = policy_service.evaluate_replenishment_policy(
        product=analysis_c["product"],
        inventory=stale,
        forecast=analysis_c["forecast"],
        replenishment=analysis_c["replenishment"],
        risk=analysis_c["risk"],
        policy=_policy(maximum_inventory_age_hours=24),
        confidence=0.95,
        history_days=30,
        order_value=100,
        as_of=datetime(2026, 7, 27, tzinfo=timezone.utc),
    )
    assert c.disposition == "blocked"

    # D — zero quantity / no order
    analysis_d = build_analysis("ST001", "SKU-1005")
    replenishment = analysis_d["replenishment"].model_copy(
        update={"recommended_quantity": 0, "days_of_supply": Decimal("20")}
    )
    d = policy_service.evaluate_replenishment_policy(
        product=analysis_d["product"],
        inventory=analysis_d["inventory"],
        forecast=analysis_d["forecast"],
        replenishment=replenishment,
        risk={"risk_level": "overstock", "reasons": ["covered"]},
        policy=policy,
        confidence=0.95,
        history_days=30,
        order_value=0,
    )
    assert d.disposition == "no_order"

    print(
        "EXAMPLES",
        {
            "SKU_A": a.disposition,
            "SKU_B": b.disposition,
            "SKU_C": c.disposition,
            "SKU_D": d.disposition,
        },
    )

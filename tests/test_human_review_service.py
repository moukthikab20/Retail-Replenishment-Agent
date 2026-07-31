"""Human review service tests."""

from __future__ import annotations

import pytest

from services import human_review_service, recommendation_service


@pytest.fixture
def recommendation_id():
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="test",
    )
    return rec.recommendation_id


def test_accept_agent_recommendation(recommendation_id):
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="use_agent",
    )
    assert preview["valid"] is True
    assert preview["override_used"] is False
    assert preview["human_proposed_quantity"] == preview["agent_recommended_quantity"]


def test_identical_quantity_does_not_require_reason(recommendation_id):
    agent_qty = recommendation_service.get_recommendation(recommendation_id)[
        "agent_recommended_quantity"
    ]
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=agent_qty,
        override_reason=None,
    )
    assert preview["valid"] is True
    assert preview["override_used"] is False


def test_lower_and_higher_human_quantity(recommendation_id):
    agent_qty = recommendation_service.get_recommendation(recommendation_id)[
        "agent_recommended_quantity"
    ]
    case_pack = recommendation_service.get_recommendation(recommendation_id)["case_pack"]
    lower = max(0, agent_qty - case_pack)
    higher = agent_qty + case_pack
    for qty in (lower, higher):
        preview = human_review_service.preview_human_review(
            recommendation_id=recommendation_id,
            choice="manual",
            human_proposed_quantity=qty,
            override_reason="Adjusting coverage",
        )
        assert preview["valid"] is True
        assert preview["human_proposed_quantity"] == qty
        assert preview["agent_recommended_quantity"] == agent_qty


def test_zero_quantity_escalation(recommendation_id):
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=0,
        override_reason="No order needed",
    )
    assert preview["valid"] is True
    assert preview["requires_escalation"] is True


def test_negative_quantity_rejected(recommendation_id):
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=-5,
        override_reason="bad",
    )
    assert preview["valid"] is False


def test_blank_override_reason_rejected(recommendation_id):
    agent_qty = recommendation_service.get_recommendation(recommendation_id)[
        "agent_recommended_quantity"
    ]
    case_pack = recommendation_service.get_recommendation(recommendation_id)["case_pack"]
    qty = agent_qty + case_pack
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=qty,
        override_reason="   ",
    )
    assert preview["valid"] is False


def test_non_case_pack_blocked(recommendation_id):
    agent_qty = recommendation_service.get_recommendation(recommendation_id)[
        "agent_recommended_quantity"
    ]
    case_pack = recommendation_service.get_recommendation(recommendation_id)["case_pack"]
    bad = agent_qty + 1 if (agent_qty + 1) % case_pack else agent_qty + 2
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=bad,
        override_reason="test",
    )
    assert preview["valid"] is False
    assert preview["case_pack_compliant"] is False
    assert preview["human_proposed_quantity"] == bad  # never silently replaced


def test_percent_thresholds(recommendation_id):
    agent_qty = recommendation_service.get_recommendation(recommendation_id)[
        "agent_recommended_quantity"
    ]
    if agent_qty == 0:
        pytest.skip("agent qty zero for this SKU in fixture data")
    # ~15% change → warning
    case_pack = recommendation_service.get_recommendation(recommendation_id)["case_pack"]
    target = int(round(agent_qty * 1.15 / case_pack) * case_pack)
    if target == agent_qty:
        target = agent_qty + case_pack
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=target,
        override_reason="coverage tweak",
    )
    assert preview["valid"] is True
    if preview["difference_percent"] > 25:
        assert preview["requires_escalation"] is True
    elif preview["difference_percent"] > 10:
        assert preview["approval_level"] in {"warning", "elevated"}

    # large jump → escalation
    big = agent_qty + case_pack * 20
    preview2 = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=big,
        override_reason="large change",
    )
    assert preview2["requires_escalation"] is True


def test_projected_risk_fields(recommendation_id):
    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="use_agent",
    )
    assert "projected_risk" in preview
    assert preview["projected_risk"] in {
        "stockout",
        "overstock",
        "balanced",
        "manual_review",
        "insufficient_data",
    }

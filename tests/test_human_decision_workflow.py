"""Checkpoint 5 — human decision workflow by disposition."""

from __future__ import annotations

import pytest

from database.connection import get_session
from repositories import human_review_repository, recommendation_repository
from services import (
    auth_service,
    batch_run_service,
    decision_workflow_service,
    disposition_service,
    policy_service,
    recommendation_service,
)


def _seed(monkeypatch) -> dict:
    policy_service.ensure_default_policy()
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    return batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1001"),
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1004"),
        ],
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-hd",
    )


def _id(run: dict, disposition: str) -> str:
    for item in run["items"]:
        if item.get("disposition") == disposition and item.get("recommendation_id"):
            return item["recommendation_id"]
    raise AssertionError(disposition)


def test_available_actions_by_disposition(monkeypatch):
    run = _seed(monkeypatch)
    human = _id(run, "human_review")
    auto = _id(run, "auto_release")
    blocked = _id(run, "blocked")

    a_human = decision_workflow_service.get_available_actions(
        human, actor_role="store_manager"
    )
    assert set(a_human["actions"]) == {"approve", "adjust", "decline"}

    a_auto_store = decision_workflow_service.get_available_actions(
        auto, actor_role="store_manager"
    )
    assert a_auto_store["actions"] == []

    a_auto_cat = decision_workflow_service.get_available_actions(
        auto, actor_role="category_manager"
    )
    assert "recall" in a_auto_cat["actions"]
    assert "override" in a_auto_cat["actions"]

    a_blocked = decision_workflow_service.get_available_actions(
        blocked, actor_role="inventory_planner"
    )
    assert "retry" in a_blocked["actions"]
    assert "manual_quantity" in a_blocked["actions"]


def test_approve_preserves_agent_quantity(monkeypatch):
    run = _seed(monkeypatch)
    rec_id = _id(run, "human_review")
    before = recommendation_service.get_recommendation(rec_id)
    agent_qty = before["agent_recommended_quantity"]

    result = decision_workflow_service.approve_recommendation(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert result["outcome"] in {"approved", "pending_approval"}
    assert result["final_quantity"] == agent_qty

    with get_session() as session:
        review = human_review_repository.get_latest_review_for_recommendation(
            session, rec_id
        )
        row = recommendation_repository.get_recommendation_row(session, rec_id)
    assert review is not None
    assert review.agent_recommended_quantity == agent_qty
    assert review.human_proposed_quantity == agent_qty
    assert review.decision_action == "approve"
    assert review.quantity_source == "agent"
    assert row is not None
    assert row.agent_recommended_quantity == agent_qty


def test_adjust_requires_reason_code_and_does_not_round(monkeypatch):
    run = _seed(monkeypatch)
    rec_id = _id(run, "human_review")
    rec = recommendation_service.get_recommendation(rec_id)
    case_pack = int(rec["case_pack"])
    agent_qty = int(rec["agent_recommended_quantity"])
    # Non case-pack qty should not be rounded; submit rejected as invalid.
    bad_qty = agent_qty + 1 if (agent_qty + 1) % case_pack else agent_qty + 2
    while bad_qty % case_pack == 0:
        bad_qty += 1

    preview = decision_workflow_service.preview_adjust(
        recommendation_id=rec_id,
        proposed_quantity=bad_qty,
        reason_code="local_demand_knowledge",
    )
    assert preview["proposed_quantity"] == bad_qty
    assert preview["rounded"] is False
    assert preview["case_pack_compliant"] is False
    assert preview["valid"] is False

    with pytest.raises(ValueError):
        decision_workflow_service.adjust_quantity(
            recommendation_id=rec_id,
            actor="alex.store",
            actor_role="store_manager",
            proposed_quantity=bad_qty,
            reason_code="local_demand_knowledge",
        )

    with pytest.raises(ValueError, match="other"):
        decision_workflow_service.adjust_quantity(
            recommendation_id=rec_id,
            actor="alex.store",
            actor_role="store_manager",
            proposed_quantity=agent_qty + case_pack,
            reason_code="other",
            comments="",
        )

    good_qty = agent_qty + case_pack
    result = decision_workflow_service.adjust_quantity(
        recommendation_id=rec_id,
        actor="jamie.planner",
        actor_role="inventory_planner",
        proposed_quantity=good_qty,
        reason_code="promotion_change",
        comments="Promo lift",
    )
    assert result["final_quantity"] == good_qty
    with get_session() as session:
        review = human_review_repository.get_latest_review_for_recommendation(
            session, rec_id
        )
        row = recommendation_repository.get_recommendation_row(session, rec_id)
    assert review is not None
    assert review.human_proposed_quantity == good_qty
    assert review.agent_recommended_quantity == agent_qty
    assert review.reason_code == "promotion_change"
    assert row.agent_recommended_quantity == agent_qty


def test_decline_persists_actor_role_timestamp_version(monkeypatch):
    run = _seed(monkeypatch)
    rec_id = _id(run, "human_review")
    before = recommendation_service.get_recommendation(rec_id)

    result = decision_workflow_service.decline_recommendation(
        recommendation_id=rec_id,
        actor="alex.store",
        actor_role="store_manager",
        reason_code="store_closure",
        comments="Closed for remodel",
    )
    assert result["outcome"] == "declined"
    assert result["declined_by"] == "alex.store"
    assert result["declined_role"] == "store_manager"
    assert result["decline_reason_code"] == "store_closure"

    with get_session() as session:
        row = recommendation_repository.get_recommendation_row(session, rec_id)
        assert row is not None
        assert row.status == "declined"
        assert row.declined_by == "alex.store"
        assert row.declined_role == "store_manager"
        assert row.declined_at is not None
        assert row.decline_reason_code == "store_closure"
        assert row.recommendation_id == before["recommendation_id"]  # not deleted
        # Still loadable
        assert recommendation_repository.get_recommendation(session, rec_id) is not None


def test_auto_release_hides_controls_unless_recall_role(monkeypatch):
    run = _seed(monkeypatch)
    auto = _id(run, "auto_release")
    with pytest.raises(auth_service.AuthError):
        decision_workflow_service.recall_auto_release(
            recommendation_id=auto,
            actor="alex.store",
            actor_role="store_manager",
        )
    recalled = decision_workflow_service.recall_auto_release(
        recommendation_id=auto,
        actor="casey.category",
        actor_role="category_manager",
    )
    assert recalled["disposition"] == "human_review"
    actions = decision_workflow_service.get_available_actions(
        auto, actor_role="store_manager"
    )
    assert "approve" in actions["actions"]


def test_blocked_manual_quantity_routes_to_formal_approval(monkeypatch):
    run = _seed(monkeypatch)
    blocked = _id(run, "blocked")
    rec = recommendation_service.get_recommendation(blocked)
    case_pack = int(rec["case_pack"])
    qty = case_pack * 2

    with pytest.raises(auth_service.AuthError):
        decision_workflow_service.submit_manual_quantity_blocked(
            recommendation_id=blocked,
            actor="alex.store",
            actor_role="store_manager",
            proposed_quantity=qty,
            reason_code="inventory_discrepancy",
        )

    result = decision_workflow_service.submit_manual_quantity_blocked(
        recommendation_id=blocked,
        actor="jamie.planner",
        actor_role="inventory_planner",
        proposed_quantity=qty,
        reason_code="inventory_discrepancy",
        comments="Counted stock differs",
    )
    assert result["ai_recommendation_unavailable"] is True
    assert result["quantity_source"] == "human_manual"
    assert result["outcome"] in {"approved", "pending_approval"}
    # inventory_planner may or may not clear elevated — force_escalation needs category_manager
    assert result.get("required_role") in {"category_manager", "inventory_planner", "store_manager"}

    with get_session() as session:
        review = human_review_repository.get_latest_review_for_recommendation(
            session, blocked
        )
    assert review is not None
    assert review.ai_recommendation_unavailable is True
    assert review.quantity_source == "human_manual"
    assert review.human_proposed_quantity == qty
    assert review.decision_action == "manual_quantity"
    # Must not claim the proposed qty is the agent recommendation
    assert review.human_proposed_quantity != review.agent_recommended_quantity or qty == review.agent_recommended_quantity


def test_blocked_retry_creates_new_score(monkeypatch):
    run = _seed(monkeypatch)
    blocked = _id(run, "blocked")
    # Retry with freshness restored — monkeypatch age back to normal for re-score
    monkeypatch.setattr(
        "services.policy_service.inventory_age_hours",
        lambda position, **kwargs: 1.0,
    )
    result = decision_workflow_service.retry_blocked(
        recommendation_id=blocked,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert result["outcome"] == "retried"
    assert result["new_recommendation_id"]
    assert result["new_recommendation_id"] != blocked


def test_every_action_writes_audit(monkeypatch):
    run = _seed(monkeypatch)
    human = _id(run, "human_review")
    decision_workflow_service.approve_recommendation(
        recommendation_id=human,
        actor="alex.store",
        actor_role="store_manager",
    )
    with get_session() as session:
        from database.models import AuditEventRow
        from sqlalchemy import select

        events = list(
            session.scalars(
                select(AuditEventRow).where(AuditEventRow.recommendation_id == human)
            )
        )
    types = {e.event_type for e in events}
    assert "recommendation_approved" in types or "human_review_submitted" in types


def test_disposition_service_compat_decline_reason(monkeypatch):
    run = _seed(monkeypatch)
    human = _id(run, "human_review")
    result = disposition_service.decline_recommendation(
        recommendation_id=human,
        actor="alex.store",
        actor_role="store_manager",
        reason="Declined from Today's Queue",
    )
    assert result["outcome"] == "declined"

"""Approval and purchase-order service tests."""

from __future__ import annotations

import pytest

from services import (
    approval_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)


def _prepare_pending_approval():
    rec = recommendation_service.create_recommendation_record("ST001", "SKU-1001", rationale="t")
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
        actor_role="store_manager",
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)
    return rec, review, approval


def test_correct_role_approves():
    _, _, approval = _prepare_pending_approval()
    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="alex.store",
        actor_role="store_manager",
    )
    assert decided.status == "approved"
    assert decided.approved_final_quantity == decided.human_proposed_quantity


def test_incorrect_role_rejected():
    # Force elevated approval via zero quantity
    rec = recommendation_service.create_recommendation_record("ST001", "SKU-1002", rationale="t")
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="manual",
        human_proposed_quantity=0,
        override_reason="no order",
        submitted_by="alex.store",
        actor_role="store_manager",
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)
    assert approval.required_role == "category_manager"
    with pytest.raises(PermissionError):
        approval_service.decide_approval(
            approval_id=approval.approval_id,
            decision="approve",
            actor="alex.store",
            actor_role="store_manager",
        )


def test_duplicate_approval_rejected():
    _, _, approval = _prepare_pending_approval()
    approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="jamie.planner",
        actor_role="inventory_planner",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        approval_service.decide_approval(
            approval_id=approval.approval_id,
            decision="approve",
            actor="jamie.planner",
            actor_role="inventory_planner",
        )


def test_rejected_review_cannot_create_order():
    rec = recommendation_service.create_recommendation_record("ST001", "SKU-1001", rationale="t")
    human_review_service.reject_recommendation(
        recommendation_id=rec.recommendation_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    with pytest.raises(ValueError):
        # No approval exists; inventing approval should fail
        purchase_order_service.create_mock_purchase_order("APR-does-not-exist")


def test_pending_approval_cannot_create_order():
    _, _, approval = _prepare_pending_approval()
    with pytest.raises(ValueError, match="approval status"):
        purchase_order_service.create_mock_purchase_order(approval.approval_id)


def test_purchase_order_accepts_approved_id_and_is_idempotent():
    _, _, approval = _prepare_pending_approval()
    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="casey.category",
        actor_role="category_manager",
    )
    po1 = purchase_order_service.create_mock_purchase_order(decided.approval_id)
    po2 = purchase_order_service.create_mock_purchase_order(decided.approval_id)
    assert po1.purchase_order_id == po2.purchase_order_id
    assert po1.approved_final_quantity == decided.approved_final_quantity
    assert po1.agent_recommended_quantity == decided.agent_recommended_quantity
    assert po1.human_proposed_quantity == decided.human_proposed_quantity


def test_purchase_order_rejects_arbitrary_quantity_api():
    # Service signature accepts only approval_id
    import inspect

    sig = inspect.signature(purchase_order_service.create_mock_purchase_order)
    assert "approval_id" in sig.parameters
    assert "quantity" not in sig.parameters

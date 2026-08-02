"""Mock purchase order service — approval_id only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database.connection import get_session
from models.purchase_order import PurchaseOrder
from repositories import (
    approval_repository,
    audit_repository,
    human_review_repository,
    purchase_order_repository,
    recommendation_repository,
)
from services import auth_service


def create_mock_purchase_order(
    approval_id: str,
    *,
    actor: str = "system",
    actor_role: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    idempotency_key: str | None = None,
) -> PurchaseOrder:
    """
    Create an idempotent mock purchase order from a verified approval.

    Accepts only approval_id (plus optional ownership/idempotency metadata).
    Never accepts an arbitrary quantity from the model.
    """
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_create_purchase_order(actor_role),
            "create a purchase order",
        )
    key = idempotency_key or f"po:{approval_id}"
    with get_session() as session:
        existing = purchase_order_repository.get_purchase_order_by_approval(session, approval_id)
        if existing is not None:
            return existing
        existing_key = purchase_order_repository.get_purchase_order_by_idempotency_key(session, key)
        if existing_key is not None:
            return existing_key

        approval = approval_repository.get_approval(session, approval_id)
        if approval is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != "approved":
            raise ValueError(
                f"Cannot create purchase order; approval status is {approval.status}"
            )
        if approval.approved_final_quantity is None:
            raise ValueError("approved_final_quantity is required to create a purchase order")

        recommendation = recommendation_repository.get_recommendation(
            session, approval.recommendation_id
        )
        if recommendation is None:
            raise ValueError("Recommendation missing for approval")
        review = human_review_repository.get_human_review(session, approval.review_id)
        if review is None:
            raise ValueError("Human review missing for approval")

        po = PurchaseOrder(
            purchase_order_id=f"PO-MOCK-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
            approval_id=approval.approval_id,
            store_id=recommendation.store_id,
            sku=recommendation.sku,
            agent_recommended_quantity=approval.agent_recommended_quantity,
            human_proposed_quantity=approval.human_proposed_quantity,
            approved_final_quantity=approval.approved_final_quantity,
            override_used=review.override_used,
            override_reason=review.override_reason,
            status="Draft — Mock ERP",
            created_at=datetime.now(timezone.utc),
            idempotency_key=key,
            user_id=user_id or approval.user_id,
            session_id=session_id or approval.session_id,
        )
        try:
            saved = purchase_order_repository.save_purchase_order(session, po)
            recommendation_repository.update_recommendation_status(
                session, recommendation.recommendation_id, "ordered"
            )
            audit_repository.write_audit_event(
                session,
                "purchase_order_created",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=recommendation.recommendation_id,
                review_id=review.review_id,
                approval_id=approval.approval_id,
                purchase_order_id=saved.purchase_order_id,
                user_id=saved.user_id,
                session_id=saved.session_id,
                details={
                    "agent_recommended_quantity": saved.agent_recommended_quantity,
                    "human_proposed_quantity": saved.human_proposed_quantity,
                    "approved_final_quantity": saved.approved_final_quantity,
                    "idempotency_key": saved.idempotency_key,
                },
            )
            return saved
        except Exception as exc:
            # Concurrent insert: return existing idempotent row if present
            raced = purchase_order_repository.get_purchase_order_by_approval(session, approval_id)
            if raced is not None:
                return raced
            audit_repository.write_audit_event(
                session,
                "purchase_order_failed",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=recommendation.recommendation_id,
                approval_id=approval.approval_id,
                details={"error": str(exc)},
            )
            raise


def get_purchase_order_status(purchase_order_id: str) -> dict[str, Any]:
    with get_session() as session:
        po = purchase_order_repository.get_purchase_order(session, purchase_order_id)
    if po is None:
        return {"purchase_order_id": purchase_order_id, "status": "not_found"}
    return po.model_dump(mode="json")

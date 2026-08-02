"""Formal approval workflow service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from config import ELEVATED_APPROVAL_ROLES, NORMAL_APPROVAL_ROLES, ROLE_CATEGORY_MANAGER
from database.connection import get_session
from models.approval import ApprovalRequest
from repositories import (
    approval_repository,
    audit_repository,
    human_review_repository,
    recommendation_repository,
)
from services import auth_service
from services.errors import IdempotencyConflictError


def _required_role_for_review(requires_escalation: bool, approval_level: str) -> str:
    if requires_escalation or approval_level == "elevated":
        return ROLE_CATEGORY_MANAGER
    if approval_level == "warning":
        return "inventory_planner"
    return "store_manager"


def create_approval_request(
    *,
    review_id: str,
    actor: str = "system",
    actor_role: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> ApprovalRequest:
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_request_approval(actor_role),
            "request approval",
        )
    with get_session() as session:
        review = human_review_repository.get_human_review(session, review_id)
        if review is None:
            raise ValueError(f"Review not found: {review_id}")
        if review.status == "rejected":
            raise ValueError("Rejected review cannot create an approval request")

        # DB unique on review_id — return any existing approval (idempotent)
        existing = approval_repository.get_latest_approval_for_review(session, review_id)
        if existing is not None:
            return existing

        required_role = _required_role_for_review(
            review.requires_escalation, review.approval_level
        )
        approval = ApprovalRequest(
            approval_id=f"APR-{uuid4().hex[:12]}",
            review_id=review.review_id,
            recommendation_id=review.recommendation_id,
            agent_recommended_quantity=review.agent_recommended_quantity,
            human_proposed_quantity=review.human_proposed_quantity,
            approved_final_quantity=None,
            required_role=required_role,
            status="pending",
            requested_at=datetime.now(timezone.utc),
            user_id=user_id or review.user_id,
            session_id=session_id or review.session_id,
        )
        try:
            with session.begin_nested():
                approval_repository.save_approval(session, approval)
        except IntegrityError as exc:
            existing_after_race = approval_repository.get_latest_approval_for_review(
                session, review_id
            )
            if existing_after_race is not None:
                return existing_after_race
            raise IdempotencyConflictError(
                "An approval request already exists for this review."
            ) from exc
        recommendation_repository.update_recommendation_status(
            session, review.recommendation_id, "pending_approval"
        )
        audit_repository.write_audit_event(
            session,
            "approval_requested",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=review.recommendation_id,
            review_id=review.review_id,
            approval_id=approval.approval_id,
            user_id=approval.user_id,
            session_id=approval.session_id,
            details={"required_role": required_role},
        )
        return approval


def decide_approval(
    *,
    approval_id: str,
    decision: str,
    actor: str,
    actor_role: str,
    rejection_reason: str | None = None,
) -> ApprovalRequest:
    """Record approve or reject. Never treats chat text as approval."""
    decision = decision.lower().strip()
    if decision not in {"approve", "reject"}:
        raise ValueError("Decision must be approve or reject")

    with get_session() as session:
        approval = approval_repository.get_approval(session, approval_id)
        if approval is None:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.status != "pending":
            raise ValueError("Duplicate approval actions are rejected")

        allowed = (
            ELEVATED_APPROVAL_ROLES
            if approval.required_role in ELEVATED_APPROVAL_ROLES
            or approval.required_role == ROLE_CATEGORY_MANAGER
            else NORMAL_APPROVAL_ROLES
        )
        # Independently verify role against required role hierarchy (not the model)
        auth_service.authorize_approval(actor_role, approval.required_role)

        now = datetime.now(timezone.utc)
        if decision == "approve":
            approval.status = "approved"
            approval.approved_final_quantity = approval.human_proposed_quantity
            approval.approved_by = actor
            approval.approved_at = now
            event = "approval_granted"
        else:
            approval.status = "rejected"
            approval.approved_final_quantity = None
            approval.approved_by = actor
            approval.approved_at = now
            approval.rejection_reason = rejection_reason or "Rejected by approver"
            event = "approval_rejected"

        approval_repository.save_approval(session, approval)
        recommendation_repository.update_recommendation_status(
            session,
            approval.recommendation_id,
            "approved" if decision == "approve" else "approval_rejected",
        )
        audit_repository.write_audit_event(
            session,
            event,
            actor=actor,
            actor_role=actor_role,
            recommendation_id=approval.recommendation_id,
            review_id=approval.review_id,
            approval_id=approval.approval_id,
            details={
                "approved_final_quantity": approval.approved_final_quantity,
                "allowed_roles_checked": sorted(allowed),
            },
        )
        return approval


def check_approval_status(approval_id: str) -> dict[str, Any]:
    with get_session() as session:
        approval = approval_repository.get_approval(session, approval_id)
    if approval is None:
        return {"approval_id": approval_id, "status": "not_found"}
    return approval.model_dump(mode="json")


def _role_satisfies(actor_role: str, required_role: str) -> bool:
    return auth_service.role_satisfies(actor_role, required_role)

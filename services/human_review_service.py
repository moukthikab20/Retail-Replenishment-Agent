"""Human replenishment review and override validation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import uuid4

from config import ESCALATION_REQUIRED_PERCENT, ESCALATION_WARNING_PERCENT
from database.connection import get_session
from models.human_review import HumanReplenishmentReview
from repositories import (
    audit_repository,
    human_review_repository,
    recommendation_repository,
)
from repositories.recommendation_repository import get_recommendation_row
from services import inventory_service, product_service, risk_service
from services.replenishment_service import nearest_case_pack_quantities


Choice = Literal["use_agent", "manual"]


def preview_human_review(
    *,
    recommendation_id: str,
    choice: Choice,
    human_proposed_quantity: int | None = None,
    override_reason: str | None = None,
) -> dict[str, Any]:
    """Validate a human proposal without persisting."""
    with get_session() as session:
        recommendation = recommendation_repository.get_recommendation(session, recommendation_id)
        row = get_recommendation_row(session, recommendation_id)
    if recommendation is None or row is None:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    agent_qty = recommendation.agent_recommended_quantity
    if choice == "use_agent":
        proposed = agent_qty
        reason = None
    else:
        if human_proposed_quantity is None:
            return _invalid(
                agent_qty,
                None,
                ["Manual replenishment quantity is required"],
            )
        proposed = human_proposed_quantity
        reason = (override_reason or "").strip() or None

    messages: list[str] = []
    blocked = False

    if not isinstance(proposed, int) or isinstance(proposed, bool):
        return _invalid(agent_qty, proposed, ["Human quantity must be a whole number"])
    if proposed < 0:
        return _invalid(agent_qty, proposed, ["Human quantity must be zero or greater"])

    product = product_service.get_product_details(recommendation.sku)
    lower, higher = nearest_case_pack_quantities(proposed, product.case_pack)
    case_pack_compliant = proposed == 0 or proposed % product.case_pack == 0
    if not case_pack_compliant:
        messages.append(
            f"Quantity {proposed} is not a multiple of case pack {product.case_pack}. "
            f"Nearest valid: lower={lower}, higher={higher}."
        )
        # Policy: do not silently replace; keep proposed, mark non-compliant for UI
        blocked = True

    if proposed > 0 and proposed < product.minimum_order_quantity:
        messages.append(
            f"Quantity {proposed} is below minimum order quantity {product.minimum_order_quantity}."
        )
        blocked = True

    if proposed > product.maximum_order_quantity:
        messages.append(
            f"Quantity {proposed} exceeds maximum order quantity {product.maximum_order_quantity}."
        )
        blocked = True

    override_used = proposed != agent_qty
    if override_used and not reason:
        messages.append("Override reason is mandatory when quantity differs from the agent recommendation.")
        blocked = True
    if not override_used:
        reason = None

    difference_units = proposed - agent_qty
    if agent_qty == 0:
        difference_percent = Decimal("100") if proposed != 0 else Decimal("0")
    else:
        difference_percent = (
            (Decimal(abs(difference_units)) / Decimal(agent_qty)) * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    inventory = inventory_service.get_inventory_position(recommendation.store_id, recommendation.sku)
    projected = risk_service.project_risk_after_order(
        usable_on_hand=inventory.usable_on_hand,
        in_transit=inventory.in_transit,
        order_quantity=proposed,
        forecast_units=recommendation.forecast_units,
    )

    approval_level = "normal"
    requires_escalation = False
    if proposed == 0:
        requires_escalation = True
        approval_level = "elevated"
        messages.append("Zero quantity requires higher approval.")
    elif difference_percent > ESCALATION_REQUIRED_PERCENT:
        requires_escalation = True
        approval_level = "elevated"
        messages.append(
            f"Change of {difference_percent}% exceeds {ESCALATION_REQUIRED_PERCENT}% escalation threshold."
        )
    elif difference_percent > ESCALATION_WARNING_PERCENT:
        approval_level = "warning"
        messages.append(
            f"Change of {difference_percent}% exceeds {ESCALATION_WARNING_PERCENT}% warning threshold."
        )

    valid = not blocked
    if valid and not messages:
        messages.append("Validation passed.")

    return {
        "valid": valid,
        "blocked": blocked,
        "recommendation_id": recommendation_id,
        "agent_recommended_quantity": agent_qty,
        "human_proposed_quantity": proposed,
        "override_used": override_used,
        "override_reason": reason,
        "difference_units": difference_units,
        "difference_percent": float(difference_percent),
        "projected_days_of_supply": projected.get("projected_days_of_supply"),
        "projected_risk": projected["risk_level"],
        "requires_escalation": requires_escalation,
        "approval_level": approval_level,
        "validation_messages": messages,
        "case_pack": product.case_pack,
        "case_pack_compliant": case_pack_compliant,
        "nearest_lower_case_pack": lower,
        "nearest_higher_case_pack": higher,
        "store_id": recommendation.store_id,
        "sku": recommendation.sku,
        "forecast_units": float(recommendation.forecast_units),
        "current_risk": recommendation.risk_level,
    }


def submit_human_review(
    *,
    recommendation_id: str,
    choice: Choice,
    submitted_by: str,
    human_proposed_quantity: int | None = None,
    override_reason: str | None = None,
    actor_role: str | None = None,
) -> HumanReplenishmentReview:
    preview = preview_human_review(
        recommendation_id=recommendation_id,
        choice=choice,
        human_proposed_quantity=human_proposed_quantity,
        override_reason=override_reason,
    )
    if not preview["valid"]:
        raise ValueError("; ".join(preview["validation_messages"]))

    review = HumanReplenishmentReview(
        review_id=f"REV-{uuid4().hex[:12]}",
        recommendation_id=recommendation_id,
        agent_recommended_quantity=preview["agent_recommended_quantity"],
        human_proposed_quantity=preview["human_proposed_quantity"],
        override_used=preview["override_used"],
        override_reason=preview["override_reason"],
        difference_units=preview["difference_units"],
        difference_percent=Decimal(str(preview["difference_percent"])),
        projected_days_of_supply=(
            Decimal(str(preview["projected_days_of_supply"]))
            if preview["projected_days_of_supply"] is not None
            else None
        ),
        projected_risk=preview["projected_risk"],
        requires_escalation=preview["requires_escalation"],
        submitted_by=submitted_by,
        submitted_at=datetime.now(timezone.utc),
        status="submitted",
        validation_messages=preview["validation_messages"],
        approval_level=preview["approval_level"],
        nearest_lower_case_pack=preview["nearest_lower_case_pack"],
        nearest_higher_case_pack=preview["nearest_higher_case_pack"],
        case_pack_compliant=preview["case_pack_compliant"],
    )

    with get_session() as session:
        human_review_repository.save_human_review(session, review)
        recommendation_repository.update_recommendation_status(
            session, recommendation_id, "human_reviewed"
        )
        if review.override_used:
            audit_repository.write_audit_event(
                session,
                "human_override_entered",
                actor=submitted_by,
                actor_role=actor_role,
                recommendation_id=recommendation_id,
                review_id=review.review_id,
                details={
                    "agent_recommended_quantity": review.agent_recommended_quantity,
                    "human_proposed_quantity": review.human_proposed_quantity,
                },
            )
        audit_repository.write_audit_event(
            session,
            "human_review_submitted",
            actor=submitted_by,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            review_id=review.review_id,
            details={"approval_level": review.approval_level},
        )
    return review


def reject_recommendation(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str | None = None,
    reason: str | None = None,
) -> None:
    with get_session() as session:
        recommendation_repository.update_recommendation_status(
            session, recommendation_id, "rejected"
        )
        audit_repository.write_audit_event(
            session,
            "recommendation_rejected",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            details={"reason": reason or "Rejected by human reviewer"},
        )


def get_human_review_status(recommendation_id: str) -> dict[str, Any]:
    with get_session() as session:
        review = human_review_repository.get_latest_review_for_recommendation(
            session, recommendation_id
        )
        recommendation = recommendation_repository.get_recommendation(session, recommendation_id)
    if review is None:
        return {
            "recommendation_id": recommendation_id,
            "status": recommendation.status if recommendation else "not_found",
            "review": None,
        }
    return {
        "recommendation_id": recommendation_id,
        "status": review.status,
        "review": review.model_dump(mode="json"),
    }


def _invalid(agent_qty: int, proposed: int | None, messages: list[str]) -> dict[str, Any]:
    return {
        "valid": False,
        "blocked": True,
        "agent_recommended_quantity": agent_qty,
        "human_proposed_quantity": proposed,
        "override_used": proposed is not None and proposed != agent_qty,
        "override_reason": None,
        "difference_units": (proposed - agent_qty) if proposed is not None else 0,
        "difference_percent": 0.0,
        "projected_days_of_supply": None,
        "projected_risk": "manual_review",
        "requires_escalation": False,
        "approval_level": "blocked",
        "validation_messages": messages,
        "case_pack_compliant": False,
        "nearest_lower_case_pack": None,
        "nearest_higher_case_pack": None,
    }

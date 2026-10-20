"""Human decision workflow from Recommendation Detail.

Actions depend on disposition. Quantities and policy impact come from
deterministic services — never from chat or silent rounding.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import (
    ADJUST_REASON_CODES,
    DECLINE_REASON_CODES,
    REASON_CODE_LABELS,
)
from database.connection import get_session, init_db
from repositories import audit_repository, recommendation_repository
from services import (
    approval_service,
    auth_service,
    batch_run_service,
    human_review_service,
    scenario_service,
)
from services.approval_service import _required_role_for_review

# Terminal for further human decisions (not policy disposition labels).
_TERMINAL = frozenset(
    {
        "approved",
        "rejected",
        "approval_rejected",
        "declined",
        "ordered",
    }
)


def reason_code_options() -> list[dict[str, str]]:
    return [
        {"code": code, "label": REASON_CODE_LABELS.get(code, code)}
        for code in ADJUST_REASON_CODES
    ]


def _validate_reason_code(reason_code: str | None, *, comments: str | None, for_decline: bool = False) -> str:
    allowed = DECLINE_REASON_CODES if for_decline else ADJUST_REASON_CODES
    code = (reason_code or "").strip()
    if code not in allowed:
        raise ValueError(
            "A valid reason code is required: " + ", ".join(allowed)
        )
    if code == "other" and not (comments or "").strip():
        raise ValueError("Comments are required when reason code is 'other'")
    return code


def _compose_reason(reason_code: str, comments: str | None) -> str:
    label = REASON_CODE_LABELS.get(reason_code, reason_code)
    text = (comments or "").strip()
    if text:
        return f"[{reason_code}] {label}: {text}"
    return f"[{reason_code}] {label}"


def _load_row(recommendation_id: str):
    with get_session() as session:
        return recommendation_repository.get_recommendation_row(session, recommendation_id)


def _result(**kwargs: Any) -> dict[str, Any]:
    return kwargs


def get_available_actions(
    recommendation_id: str,
    *,
    actor_role: str,
) -> dict[str, Any]:
    """Return which Decision actions the role may use for this disposition."""
    init_db()
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    disposition = row.disposition or "human_review"
    status = row.status or "pending_review"
    terminal = status in _TERMINAL
    actions: list[str] = []
    notes: list[str] = []

    if terminal:
        notes.append(f"Already decided (status={status}).")
        return {
            "recommendation_id": recommendation_id,
            "disposition": disposition,
            "status": status,
            "terminal": True,
            "actions": [],
            "notes": notes,
            "reason_codes": reason_code_options(),
        }

    if disposition == "human_review":
        if auth_service.can_submit_human_review(actor_role):
            actions.extend(["approve", "adjust", "decline"])
        else:
            notes.append("Your role can view but cannot decide this item.")
    elif disposition == "auto_release":
        notes.append("Auto-released — normal review controls are hidden.")
        if auth_service.can_recall_auto_release(actor_role):
            actions.extend(["recall", "override", "decline"])
            notes.append("Your role may recall or override this auto-release.")
        else:
            notes.append("Recall/override requires category manager or higher.")
    elif disposition == "blocked":
        if auth_service.can_retry_blocked(actor_role):
            actions.append("retry")
        if auth_service.can_manual_quantity_blocked(actor_role):
            actions.append("manual_quantity")
            notes.append(
                "Manual quantity identifies that the AI recommendation was unavailable "
                "and always routes to formal approval."
            )
        if auth_service.can_submit_human_review(actor_role):
            actions.append("decline")
        if not actions:
            notes.append("No blocked-item actions are available for your role.")
    elif disposition == "no_order":
        if auth_service.can_submit_human_review(actor_role):
            actions.append("decline")
        notes.append("No order was recommended; approval is not required.")
    else:
        notes.append(f"Disposition '{disposition}' has no decision actions.")

    return {
        "recommendation_id": recommendation_id,
        "disposition": disposition,
        "status": status,
        "terminal": False,
        "actions": actions,
        "notes": notes,
        "reason_codes": reason_code_options(),
        "recommendation_version": getattr(row, "recommendation_version", 1) or 1,
        "ai_recommendation_unavailable": disposition == "blocked",
    }


def preview_adjust(
    *,
    recommendation_id: str,
    proposed_quantity: int,
    reason_code: str | None = None,
    comments: str | None = None,
) -> dict[str, Any]:
    """Deterministic scenario evaluation before adjust / manual submit."""
    init_db()
    scenario = scenario_service.evaluate_quantity_scenario(
        recommendation_id, int(proposed_quantity)
    )
    reason_ok = True
    reason_error = None
    try:
        if reason_code is not None:
            _validate_reason_code(reason_code, comments=comments)
    except ValueError as exc:
        reason_ok = False
        reason_error = str(exc)

    override_reason = None
    if reason_code:
        try:
            code = _validate_reason_code(reason_code, comments=comments)
            override_reason = _compose_reason(code, comments)
        except ValueError:
            override_reason = comments or reason_code

    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        human_proposed_quantity=int(proposed_quantity),
        override_reason=override_reason,
    )
    required_role = _required_role_for_review(
        bool(preview.get("requires_escalation")),
        str(preview.get("approval_level") or "normal"),
    )
    additional_approval = bool(preview.get("requires_escalation")) or preview.get(
        "approval_level"
    ) in {"warning", "elevated"}

    policy_impact = {
        "summary": scenario.get("summary") or scenario.get("impact") or "",
        "requires_escalation": bool(preview.get("requires_escalation")),
        "approval_level": preview.get("approval_level"),
        "additional_approval_required": additional_approval,
        "required_role": required_role,
        "case_pack_compliant": scenario.get("case_pack_compliant"),
        "warnings": list(scenario.get("warning_messages") or []),
    }

    return {
        "recommendation_id": recommendation_id,
        "agent_quantity": scenario["agent_recommended_quantity"],
        "proposed_quantity": scenario["proposed_quantity"],
        "difference_units": scenario["difference_units"],
        "difference_percent": scenario["difference_percent"],
        "projected_days_of_supply": scenario.get("projected_days_of_supply"),
        "projected_risk": scenario.get("projected_risk"),
        "case_pack_compliant": scenario.get("case_pack_compliant"),
        "nearest_lower_case_pack": scenario.get("nearest_lower_valid_quantity"),
        "nearest_higher_case_pack": scenario.get("nearest_higher_valid_quantity"),
        "policy_impact": policy_impact,
        "additional_approval_required": additional_approval,
        "required_role": required_role,
        "valid": bool(preview.get("valid")) and reason_ok,
        "validation_messages": list(preview.get("validation_messages") or [])
        + ([reason_error] if reason_error else []),
        "rounded": False,
        "scenario": scenario,
        "preview": preview,
    }


def _finalize_approval(
    *,
    review,
    actor: str,
    actor_role: str,
    user_id: str | None,
    session_id: str | None,
    action: str,
) -> dict[str, Any]:
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor=actor,
        actor_role=actor_role,
        user_id=user_id or actor,
        session_id=session_id,
    )
    if auth_service.can_approve(actor_role, approval.required_role):
        decided = approval_service.decide_approval(
            approval_id=approval.approval_id,
            decision="approve",
            actor=actor,
            actor_role=actor_role,
        )
        # Ops-platform path: queue OrderIntent at pending_erp (not transmitted).
        from services import order_lifecycle_service

        order_lifecycle_service.queue_approved_order(
            approval_id=decided.approval_id,
            actor=actor,
            actor_role=None,
            user_id=user_id or actor,
            session_id=session_id,
            released_by_type="human",
        )
        return _result(
            recommendation_id=review.recommendation_id,
            action=action,
            outcome="approved",
            status="approved",
            final_quantity=decided.approved_final_quantity,
            review_id=review.review_id,
            approval_id=decided.approval_id,
            required_role=decided.required_role,
            message="Approved",
            quantity_source=review.quantity_source,
            ai_recommendation_unavailable=review.ai_recommendation_unavailable,
        )
    return _result(
        recommendation_id=review.recommendation_id,
        action=action,
        outcome="pending_approval",
        status="pending_approval",
        final_quantity=review.human_proposed_quantity,
        review_id=review.review_id,
        approval_id=approval.approval_id,
        required_role=approval.required_role,
        message=f"Submitted; awaiting {approval.required_role} approval",
        quantity_source=review.quantity_source,
        ai_recommendation_unavailable=review.ai_recommendation_unavailable,
    )


def approve_recommendation(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Approve using agent quantity; preserve agent_recommended_quantity."""
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_submit_human_review(actor_role),
        "approve a recommendation",
    )
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError("Recommendation not found")
    if row.status == "approved":
        return _result(
            recommendation_id=recommendation_id,
            action="approve",
            outcome="already_approved",
            status="approved",
            final_quantity=row.agent_recommended_quantity,
            message="Already approved",
        )
    if row.status in _TERMINAL:
        raise ValueError(f"Already decided (status={row.status})")
    if (row.disposition or "") != "human_review":
        raise ValueError("Approve is only available for human_review disposition")

    agent_qty = int(row.agent_recommended_quantity)
    review = human_review_service.submit_human_review(
        recommendation_id=recommendation_id,
        choice="use_agent",
        submitted_by=actor,
        actor_role=actor_role,
        user_id=user_id or actor,
        session_id=session_id,
        decision_action="approve",
        quantity_source="agent",
        ai_recommendation_unavailable=False,
    )
    assert review.human_proposed_quantity == agent_qty
    assert review.agent_recommended_quantity == agent_qty

    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "recommendation_approved",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            review_id=review.review_id,
            store_id=row.store_id,
            sku=row.sku,
            details={
                "human_proposed_quantity": review.human_proposed_quantity,
                "agent_recommended_quantity": review.agent_recommended_quantity,
                "recommendation_version": getattr(row, "recommendation_version", 1),
                "store_id": row.store_id,
                "sku": row.sku,
            },
        )

    return _finalize_approval(
        review=review,
        actor=actor,
        actor_role=actor_role,
        user_id=user_id,
        session_id=session_id,
        action="approve",
    )


def adjust_quantity(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    proposed_quantity: int,
    reason_code: str,
    comments: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Adjust quantity with controlled reason codes; never silently rounds."""
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_submit_human_review(actor_role),
        "adjust a recommendation",
    )
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError("Recommendation not found")
    if row.status in _TERMINAL:
        raise ValueError(f"Already decided (status={row.status})")
    disposition = row.disposition or "human_review"
    if disposition == "human_review":
        pass
    elif disposition == "auto_release" and auth_service.can_recall_auto_release(actor_role):
        pass
    else:
        raise ValueError("Adjust is not available for this disposition/role")

    code = _validate_reason_code(reason_code, comments=comments)
    composed = _compose_reason(code, comments)
    evaluation = preview_adjust(
        recommendation_id=recommendation_id,
        proposed_quantity=int(proposed_quantity),
        reason_code=code,
        comments=comments,
    )
    if not evaluation["valid"]:
        raise ValueError("; ".join(evaluation["validation_messages"]))
    if evaluation["proposed_quantity"] != int(proposed_quantity):
        raise ValueError("Proposed quantity was altered unexpectedly; submit aborted")

    if disposition == "auto_release":
        with get_session() as session:
            recommendation_repository.update_recommendation_workflow(
                session,
                recommendation_id,
                disposition="human_review",
                status="pending_review",
            )
            audit_repository.write_audit_event(
                session,
                "auto_release_recalled_for_override",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=recommendation_id,
                details={"reason_code": code},
            )

    review = human_review_service.submit_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        submitted_by=actor,
        human_proposed_quantity=int(proposed_quantity),
        override_reason=composed,
        actor_role=actor_role,
        user_id=user_id or actor,
        session_id=session_id,
        reason_code=code,
        comments=comments,
        decision_action="adjust",
        quantity_source="human",
        ai_recommendation_unavailable=False,
    )
    assert review.human_proposed_quantity == int(proposed_quantity)

    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "recommendation_adjusted",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            review_id=review.review_id,
            store_id=row.store_id,
            sku=row.sku,
            details={
                "proposed_quantity": proposed_quantity,
                "previous_quantity": review.agent_recommended_quantity,
                "new_quantity": proposed_quantity,
                "adjusted_quantity": proposed_quantity,
                "reason_code": code,
                "comments": comments,
                "agent_recommended_quantity": review.agent_recommended_quantity,
                "recommendation_version": getattr(row, "recommendation_version", 1),
                "rounded": False,
                "store_id": row.store_id,
                "sku": row.sku,
            },
        )

    return _finalize_approval(
        review=review,
        actor=actor,
        actor_role=actor_role,
        user_id=user_id,
        session_id=session_id,
        action="adjust",
    )


def decline_recommendation(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    reason_code: str,
    comments: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Decline without deleting the recommendation."""
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_submit_human_review(actor_role),
        "decline a recommendation",
    )
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError("Recommendation not found")
    if row.status in {"rejected", "declined"}:
        return _result(
            recommendation_id=recommendation_id,
            action="decline",
            outcome="already_declined",
            status="declined",
            message="Already declined",
        )
    if row.status in _TERMINAL:
        raise ValueError(f"Already decided (status={row.status})")

    code = _validate_reason_code(reason_code, comments=comments, for_decline=True)
    composed = _compose_reason(code, comments)
    version = int(getattr(row, "recommendation_version", 1) or 1)
    now = datetime.now(timezone.utc)

    with get_session() as session:
        recommendation_repository.update_recommendation_workflow(
            session,
            recommendation_id,
            status="declined",
            declined_by=actor,
            declined_role=actor_role,
            declined_at=now,
            decline_reason=composed,
            decline_reason_code=code,
        )
        audit_repository.write_audit_event(
            session,
            "recommendation_declined",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            store_id=row.store_id,
            sku=row.sku,
            user_id=user_id or actor,
            session_id=session_id,
            details={
                "reason_code": code,
                "reason": composed,
                "comments": comments,
                "recommendation_version": version,
                "declined_at": now.isoformat(),
                "disposition": row.disposition,
                "store_id": row.store_id,
                "sku": row.sku,
            },
        )

    return _result(
        recommendation_id=recommendation_id,
        action="decline",
        outcome="declined",
        status="declined",
        message="Declined",
        declined_by=actor,
        declined_role=actor_role,
        declined_at=now.isoformat(),
        decline_reason_code=code,
        recommendation_version=version,
    )


def recall_auto_release(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    comments: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Pull an auto-released item back into human_review."""
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_recall_auto_release(actor_role),
        "recall an auto-released recommendation",
    )
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError("Recommendation not found")
    if (row.disposition or "") != "auto_release":
        raise ValueError("Only auto-released recommendations can be recalled")
    if row.status in _TERMINAL:
        raise ValueError(f"Already decided (status={row.status})")

    with get_session() as session:
        recommendation_repository.update_recommendation_workflow(
            session,
            recommendation_id,
            disposition="human_review",
            status="pending_review",
        )
        audit_repository.write_audit_event(
            session,
            "auto_release_recalled",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            user_id=user_id or actor,
            session_id=session_id,
            details={"comments": comments},
        )

    return _result(
        recommendation_id=recommendation_id,
        action="recall",
        outcome="recalled",
        status="pending_review",
        disposition="human_review",
        message="Recalled to human review",
    )


def retry_blocked(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Re-score a blocked store/SKU; returns the new recommendation id."""
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_retry_blocked(actor_role),
        "retry a blocked recommendation",
    )
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError("Recommendation not found")
    if (row.disposition or "") != "blocked":
        raise ValueError("Retry is only available for blocked recommendations")

    batch = batch_run_service.run_replenishment_batch(
        [(row.store_id, row.sku)],
        trigger_type="retry",
        initiated_by=actor,
        user_id=user_id or actor,
        session_id=session_id,
    )
    new_id = None
    new_disposition = None
    for item in batch.get("items") or []:
        if item.get("recommendation_id"):
            new_id = item["recommendation_id"]
            new_disposition = item.get("disposition")
            break

    with get_session() as session:
        version = int(getattr(row, "recommendation_version", 1) or 1) + 1
        recommendation_repository.update_recommendation_workflow(
            session,
            recommendation_id,
            recommendation_version=version,
        )
        audit_repository.write_audit_event(
            session,
            "blocked_recommendation_retried",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            run_id=batch.get("run_id"),
            details={
                "new_recommendation_id": new_id,
                "new_disposition": new_disposition,
                "prior_version": version - 1,
            },
        )

    return _result(
        recommendation_id=recommendation_id,
        action="retry",
        outcome="retried",
        status=row.status,
        new_recommendation_id=new_id,
        new_disposition=new_disposition,
        run_id=batch.get("run_id"),
        message="Re-scored; open the new recommendation if disposition changed",
    )


def submit_manual_quantity_blocked(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    proposed_quantity: int,
    reason_code: str,
    comments: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Manual quantity when AI recommendation is unavailable (blocked).

    Always routes to formal approval. Never claims the quantity came from the agent.
    """
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_manual_quantity_blocked(actor_role),
        "enter a manual quantity for a blocked recommendation",
    )
    row = _load_row(recommendation_id)
    if row is None:
        raise ValueError("Recommendation not found")
    if (row.disposition or "") != "blocked":
        raise ValueError("Manual quantity is only for blocked recommendations")
    if row.status in _TERMINAL:
        raise ValueError(f"Already decided (status={row.status})")

    code = _validate_reason_code(reason_code, comments=comments)
    composed = _compose_reason(code, comments)
    evaluation = preview_adjust(
        recommendation_id=recommendation_id,
        proposed_quantity=int(proposed_quantity),
        reason_code=code,
        comments=comments,
    )
    if not evaluation["valid"]:
        raise ValueError("; ".join(evaluation["validation_messages"]))

    # Move disposition to human_review for formal approval routing, but mark AI unavailable.
    with get_session() as session:
        recommendation_repository.update_recommendation_workflow(
            session,
            recommendation_id,
            disposition="human_review",
            status="pending_review",
        )

    review = human_review_service.submit_human_review(
        recommendation_id=recommendation_id,
        choice="manual",
        submitted_by=actor,
        human_proposed_quantity=int(proposed_quantity),
        override_reason=composed,
        actor_role=actor_role,
        user_id=user_id or actor,
        session_id=session_id,
        reason_code=code,
        comments=comments,
        decision_action="manual_quantity",
        quantity_source="human_manual",
        ai_recommendation_unavailable=True,
        force_escalation=True,
    )
    assert review.quantity_source == "human_manual"
    assert review.ai_recommendation_unavailable is True
    assert review.human_proposed_quantity == int(proposed_quantity)

    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "blocked_manual_quantity_submitted",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=recommendation_id,
            review_id=review.review_id,
            details={
                "proposed_quantity": proposed_quantity,
                "reason_code": code,
                "ai_recommendation_unavailable": True,
                "quantity_source": "human_manual",
                "agent_recommended_quantity_snapshot": review.agent_recommended_quantity,
                "note": "Human quantity — AI recommendation was unavailable",
                "recommendation_version": getattr(row, "recommendation_version", 1),
            },
        )

    result = _finalize_approval(
        review=review,
        actor=actor,
        actor_role=actor_role,
        user_id=user_id,
        session_id=session_id,
        action="manual_quantity",
    )
    # Prefer pending formal approval for blocked manual even if role can approve —
    # force_escalation sets elevated; category_manager can still auto-approve.
    result["ai_recommendation_unavailable"] = True
    result["quantity_source"] = "human_manual"
    result["message"] = (
        result.get("message")
        + " (manual quantity; AI recommendation was unavailable)"
    )
    return result

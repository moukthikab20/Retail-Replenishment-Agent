"""Queue-scale human dispositions — delegates to decision_workflow_service.

Kept for Today's Queue bulk approve and backward-compatible call sites.
"""

from __future__ import annotations

from typing import Any, Literal

from database.connection import get_session, init_db
from repositories import recommendation_repository, run_repository
from services import (
    auth_service,
    decision_workflow_service,
    human_review_service,
)
from services.approval_service import _required_role_for_review

Action = Literal["approve", "adjust", "decline"]

_TERMINAL_STATUSES = frozenset(
    {"approved", "rejected", "approval_rejected", "ordered"}
)


def _result(
    *,
    recommendation_id: str,
    action: str,
    outcome: str,
    status: str,
    final_quantity: int | None = None,
    review_id: str | None = None,
    approval_id: str | None = None,
    required_role: str | None = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "recommendation_id": recommendation_id,
        "action": action,
        "outcome": outcome,
        "status": status,
        "final_quantity": final_quantity,
        "review_id": review_id,
        "approval_id": approval_id,
        "required_role": required_role,
        "message": message,
    }


def _load_row(recommendation_id: str):
    with get_session() as session:
        return recommendation_repository.get_recommendation_row(session, recommendation_id)


def approve_recommendation(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    human_proposed_quantity: int | None = None,
    override_reason: str | None = None,
    reason_code: str | None = None,
    comments: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Approve as recommended, or adjust when a proposed quantity is provided."""
    if human_proposed_quantity is None:
        return decision_workflow_service.approve_recommendation(
            recommendation_id=recommendation_id,
            actor=actor,
            actor_role=actor_role,
            user_id=user_id,
            session_id=session_id,
        )

    code = reason_code or "other"
    note = comments if comments is not None else override_reason
    return decision_workflow_service.adjust_quantity(
        recommendation_id=recommendation_id,
        actor=actor,
        actor_role=actor_role,
        proposed_quantity=int(human_proposed_quantity),
        reason_code=code,
        comments=note,
        user_id=user_id,
        session_id=session_id,
    )


def decline_recommendation(
    *,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    reason: str | None = None,
    reason_code: str | None = None,
    comments: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Decline a queue recommendation. Does not create a purchase order."""
    code = reason_code or "other"
    note = comments if comments is not None else reason
    if code == "other" and not (note or "").strip():
        note = reason or "Declined from Today's Queue"
    return decision_workflow_service.decline_recommendation(
        recommendation_id=recommendation_id,
        actor=actor,
        actor_role=actor_role,
        reason_code=code,
        comments=note,
        user_id=user_id,
        session_id=session_id,
    )


def is_within_policy_for_bulk(
    *,
    recommendation_id: str,
    actor_role: str,
) -> bool:
    row = _load_row(recommendation_id)
    if row is None:
        return False
    if (row.disposition or "human_review") != "human_review":
        return False
    if row.status in _TERMINAL_STATUSES or row.status == "pending_approval":
        return False

    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice="use_agent",
    )
    if not preview.get("valid"):
        return False
    if preview.get("requires_escalation"):
        return False
    required = _required_role_for_review(
        bool(preview.get("requires_escalation")),
        str(preview.get("approval_level") or "normal"),
    )
    return auth_service.can_approve(actor_role, required)


def approve_all_within_policy(
    *,
    actor: str,
    actor_role: str,
    run_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    init_db()
    auth_service.require_permission(
        actor_role,
        auth_service.can_submit_human_review(actor_role),
        "bulk-approve within policy",
    )

    with get_session() as session:
        if run_id:
            run = run_repository.get_run(session, run_id)
        else:
            run = run_repository.get_latest_run(session, terminal_only=True)
        if run is None:
            return {
                "run_id": None,
                "attempted": 0,
                "approved": 0,
                "pending_approval": 0,
                "skipped": 0,
                "failed": 0,
                "results": [],
            }
        recommendations = run_repository.list_recommendations_for_run(session, run.run_id)
        candidates = [
            r
            for r in recommendations
            if (r.disposition or "") == "human_review"
            and r.status not in _TERMINAL_STATUSES
            and r.status != "pending_approval"
        ]
        active_run_id = run.run_id

    results: list[dict[str, Any]] = []
    approved = pending = skipped = failed = 0
    for rec in candidates:
        if not is_within_policy_for_bulk(
            recommendation_id=rec.recommendation_id,
            actor_role=actor_role,
        ):
            skipped += 1
            results.append(
                _result(
                    recommendation_id=rec.recommendation_id,
                    action="approve",
                    outcome="skipped",
                    status=rec.status,
                    message="Not within policy for bulk approve",
                )
            )
            continue
        try:
            outcome = approve_recommendation(
                recommendation_id=rec.recommendation_id,
                actor=actor,
                actor_role=actor_role,
                user_id=user_id or actor,
                session_id=session_id,
            )
            results.append(outcome)
            if outcome["outcome"] == "approved":
                approved += 1
            elif outcome["outcome"] == "pending_approval":
                pending += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results.append(
                _result(
                    recommendation_id=rec.recommendation_id,
                    action="approve",
                    outcome="failed",
                    status=rec.status,
                    message=str(exc),
                )
            )

    return {
        "run_id": active_run_id,
        "attempted": len(candidates),
        "approved": approved,
        "pending_approval": pending,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }

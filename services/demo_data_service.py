"""Idempotent demo seed and administrator reset for workflow tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select

from database.connection import get_session, init_db
from database.models import (
    AgentRunStateRow,
    ApprovalRow,
    AuditEventRow,
    HumanReviewRow,
    PurchaseOrderRow,
    RecommendationRow,
)
from repositories import audit_repository
from services import auth_service, recommendation_service

SEED_MARKER_EVENT = "demo_data_seeded"
SEED_ACTOR = "demo_seed"


def reset_demo_workflow_data(*, actor: str, actor_role: str) -> dict[str, Any]:
    """Delete workflow/runtime rows. Does not touch CSV master data."""
    auth_service.require_permission(
        actor_role,
        auth_service.can_reset_demo(actor_role),
        "reset demo data",
    )
    init_db()
    deleted: dict[str, int] = {}
    with get_session() as session:
        for model, name in (
            (PurchaseOrderRow, "purchase_orders"),
            (ApprovalRow, "approvals"),
            (HumanReviewRow, "human_reviews"),
            (AgentRunStateRow, "agent_run_states"),
            (AuditEventRow, "audit_events"),
            (RecommendationRow, "recommendations"),
        ):
            result = session.execute(delete(model))
            deleted[name] = int(result.rowcount or 0)
        audit_repository.write_audit_event(
            session,
            "demo_data_reset",
            actor=actor,
            actor_role=actor_role,
            details={"deleted": deleted},
        )
    return {"status": "reset", "deleted": deleted}


def seed_demo_data(*, force: bool = False) -> dict[str, Any]:
    """
    Idempotent seed of a small workflow sample.

    Safe to run multiple times: skips when a seed marker audit event exists,
    unless force=True.
    """
    init_db()
    with get_session() as session:
        existing = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.event_type == SEED_MARKER_EVENT)
            .limit(1)
        ).first()
        if existing is not None and not force:
            return {
                "status": "skipped",
                "reason": "demo data already seeded",
                "seed_event_id": existing.event_id,
            }

    samples = [
        ("ST001", "SKU-1001", "seed-user-a", "SESS-seed-a"),
        ("ST002", "SKU-1002", "seed-user-b", "SESS-seed-b"),
    ]
    created_ids: list[str] = []
    for store_id, sku, user_id, session_id in samples:
        rec = recommendation_service.create_recommendation_record(
            store_id,
            sku,
            rationale=f"Seeded demo recommendation for {store_id}/{sku}",
            actor=SEED_ACTOR,
            user_id=user_id,
            session_id=session_id,
            enforce_rate_limit=False,
        )
        created_ids.append(rec.recommendation_id)

    with get_session() as session:
        event_id = audit_repository.write_audit_event(
            session,
            SEED_MARKER_EVENT,
            actor=SEED_ACTOR,
            actor_role="administrator",
            details={
                "recommendation_ids": created_ids,
                "seeded_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return {
        "status": "seeded",
        "recommendation_ids": created_ids,
        "seed_event_id": event_id,
    }


def reset_and_seed(*, actor: str, actor_role: str) -> dict[str, Any]:
    reset_result = reset_demo_workflow_data(actor=actor, actor_role=actor_role)
    seed_result = seed_demo_data(force=True)
    return {"reset": reset_result, "seed": seed_result}


def ensure_demo_ready() -> dict[str, Any]:
    """Called at startup/deploy: init schema and seed if empty."""
    init_db()
    with get_session() as session:
        count = session.scalar(select(RecommendationRow.recommendation_id).limit(1))
    if count is None:
        return seed_demo_data(force=False)
    return seed_demo_data(force=False)

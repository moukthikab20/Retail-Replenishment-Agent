"""Idempotent demo seed and administrator reset for workflow tables."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from config import DATA_DIR
from database.connection import get_session, init_db
from database.models import (
    AgentRunStateRow,
    ApprovalRow,
    AuditEventRow,
    ErpOutboxRow,
    FollowUpSessionMessageRow,
    HumanReviewRow,
    OrderIntentRow,
    PolicyConfigRow,
    PurchaseOrderRow,
    RecommendationRow,
    ReplenishmentRunItemRow,
    ReplenishmentRunRow,
)
from repositories import audit_repository, csv_repository
from services import auth_service, policy_service
from services.demo_history_generator import (
    print_outcome_summary,
    regenerate_all,
    seed_historical_workflow,
)

SEED_MARKER_EVENT = "demo_data_seeded"
SEED_ACTOR = "demo_seed"


def _masters_present(data_dir: Path | None = None) -> bool:
    root = Path(data_dir or DATA_DIR)
    return all(
        (root / name).exists()
        for name in ("products.csv", "inventory.csv", "sales.csv")
    )


def ensure_demo_master_data(
    *,
    regenerate: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Ensure expanded products/inventory/sales CSVs exist (deterministic)."""
    if regenerate or not _masters_present():
        stats = regenerate_all(seed=seed)
        csv_repository.clear_csv_cache()
        return {"status": "regenerated", **stats}
    csv_repository.clear_csv_cache()
    return {"status": "present", "data_dir": str(DATA_DIR)}


def _clear_workflow_tables(*, actor: str = SEED_ACTOR, actor_role: str = "administrator") -> dict[str, int]:
    deleted: dict[str, int] = {}
    with get_session() as session:
        for model, name in (
            (ErpOutboxRow, "erp_outbox"),
            (OrderIntentRow, "order_intents"),
            (PurchaseOrderRow, "purchase_orders"),
            (ApprovalRow, "approvals"),
            (HumanReviewRow, "human_reviews"),
            (AgentRunStateRow, "agent_run_states"),
            (FollowUpSessionMessageRow, "agent_follow_up_messages"),
            (ReplenishmentRunItemRow, "replenishment_run_items"),
            (ReplenishmentRunRow, "replenishment_runs"),
            (PolicyConfigRow, "policy_configs"),
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
            details={"deleted": deleted, "source": "seed_demo_data"},
        )
    return deleted


def reset_demo_workflow_data(*, actor: str, actor_role: str) -> dict[str, Any]:
    """Delete workflow/runtime rows. Does not touch CSV master data."""
    auth_service.require_permission(
        actor_role,
        auth_service.can_reset_demo(actor_role),
        "reset demo data",
    )
    init_db()
    deleted = _clear_workflow_tables(actor=actor, actor_role=actor_role)
    policy_service.ensure_default_policy(created_by=actor)
    return {"status": "reset", "deleted": deleted}


def seed_demo_data(
    *,
    force: bool = False,
    regenerate_csvs: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """
    Idempotent seed of expanded historical workflow sample.

    Safe to run multiple times: skips when a seed marker audit event exists,
    unless force=True. Master CSVs are written when missing (or regenerate_csvs).
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

    masters = ensure_demo_master_data(
        regenerate=regenerate_csvs or seed is not None,
        seed=seed,
    )
    if force:
        deleted = _clear_workflow_tables()
        policy_service.ensure_default_policy(created_by=SEED_ACTOR)
    else:
        deleted = {}

    history = seed_historical_workflow(seed=seed)
    if history.get("generated_outcome_summary"):
        print_outcome_summary(
            history["generated_outcome_summary"],
            title=f"Generated history used for seed (seed={history.get('seed')})",
        )
    if history.get("database_outcome_summary"):
        print_outcome_summary(
            history["database_outcome_summary"],
            title="Seeded database outcome counts",
        )

    with get_session() as session:
        event_id = audit_repository.write_audit_event(
            session,
            SEED_MARKER_EVENT,
            actor=SEED_ACTOR,
            actor_role="administrator",
            details={
                "seeded_at": datetime.now(timezone.utc).isoformat(),
                "seed": history.get("seed"),
                "deleted": deleted,
                "masters": masters,
                "history": {
                    "decision_count": history.get("decision_count"),
                    "order_count": history.get("order_count"),
                    "outcome_counts": history.get("outcome_counts"),
                    "generated_outcome_summary": history.get("generated_outcome_summary"),
                    "database_outcome_summary": history.get("database_outcome_summary"),
                    "stores": history.get("stores"),
                    "skus": history.get("skus"),
                    "vendors": history.get("vendors"),
                    "history_days": history.get("history_days"),
                    "sales_rows": history.get("sales_rows"),
                },
            },
        )
    return {
        **history,
        "status": "seeded",
        "seed_event_id": event_id,
        "masters": masters,
        "deleted": deleted,
    }


def reset_and_seed(*, actor: str, actor_role: str) -> dict[str, Any]:
    reset_result = reset_demo_workflow_data(actor=actor, actor_role=actor_role)
    seed_result = seed_demo_data(force=True)
    return {"reset": reset_result, "seed": seed_result}


def ensure_demo_ready() -> dict[str, Any]:
    """Called at startup/deploy: init schema, ensure masters, seed if empty."""
    init_db()
    ensure_demo_master_data(regenerate=False)
    with get_session() as session:
        count = session.scalar(select(RecommendationRow.recommendation_id).limit(1))
    if count is None:
        return seed_demo_data(force=False)
    return seed_demo_data(force=False)

"""Synchronous batch replenishment run orchestration.

Scores many store/SKU pairs using existing deterministic services.
One item failure does not abort the batch. Safe to resume the same run_id.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence
from uuid import uuid4

from config import OPENAI_MODEL
from database.connection import get_session, init_db
from models.replenishment_run import BatchRunResult, ReplenishmentRun, ReplenishmentRunItem
from repositories import audit_repository, run_repository
from services import (
    audit_service,
    forecast_service,
    inventory_service,
    order_lifecycle_service,
    policy_service,
    product_service,
    recommendation_service,
    replenishment_service,
    risk_service,
)

_TERMINAL_RUN_STATUSES = frozenset({"completed", "completed_with_errors", "failed"})


def list_eligible_store_sku_pairs(
    pairs: Sequence[tuple[str, str]] | None = None,
    *,
    store_ids: Sequence[str] | None = None,
    sku_ids: Sequence[str] | None = None,
) -> list[tuple[str, str]]:
    """Return store/SKU combinations to score (explicit list, filters, or full catalog)."""
    if pairs is not None:
        cleaned: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for store_id, sku in pairs:
            key = (str(store_id).strip(), str(sku).strip())
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            cleaned.append(key)
        return cleaned

    store_filter = {str(s).strip() for s in (store_ids or []) if str(s).strip()} or None
    sku_filter = {str(s).strip() for s in (sku_ids or []) if str(s).strip()} or None

    result: list[tuple[str, str]] = []
    for store in product_service.list_stores():
        store_id = store["store_id"]
        if store_filter is not None and store_id not in store_filter:
            continue
        for sku in product_service.list_store_skus(store_id):
            if sku_filter is not None and sku not in sku_filter:
                continue
            result.append((store_id, sku))
    return result


def get_replenishment_run(run_id: str) -> dict[str, Any]:
    init_db()
    with get_session() as session:
        run = run_repository.get_run(session, run_id)
        if run is None:
            raise ValueError(f"Replenishment run not found: {run_id}")
        items = run_repository.list_run_items(session, run_id)
        recommendations = run_repository.list_recommendations_for_run(session, run_id)
    return _batch_result_from_run(
        run, items, recommendations, errors=[], idempotent_replay=False
    ).to_dict()


def run_replenishment_batch(
    store_sku_pairs: Sequence[tuple[str, str]] | None = None,
    *,
    trigger_type: str = "manual",
    initiated_by: str = "system",
    run_id: str | None = None,
    policy_version: str | None = None,
    model_name: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    store_ids: Sequence[str] | None = None,
    sku_ids: Sequence[str] | None = None,
    invocation_key: str | None = None,
    scheduled_for: datetime | None = None,
) -> dict[str, Any]:
    """
    Score many store/SKU combinations under one ReplenishmentRun.

    INTERNAL / LOW-LEVEL API — prefer scheduler_service.trigger_replenishment_run
    for production CLI / Admin / cron entry points.

    Returns a dict shaped like BatchRunResult (backwards compatible).
    Idempotent for a given run_id: completed runs are returned as-is;
    in-progress/retry runs skip items that already have outcomes.
    """
    return run_replenishment_batch_result(
        store_sku_pairs,
        trigger_type=trigger_type,
        initiated_by=initiated_by,
        run_id=run_id,
        policy_version=policy_version,
        model_name=model_name,
        user_id=user_id,
        session_id=session_id,
        store_ids=store_ids,
        sku_ids=sku_ids,
        invocation_key=invocation_key,
        scheduled_for=scheduled_for,
    ).to_dict()


def run_replenishment_batch_result(
    store_sku_pairs: Sequence[tuple[str, str]] | None = None,
    *,
    trigger_type: str = "manual",
    initiated_by: str = "system",
    run_id: str | None = None,
    policy_version: str | None = None,
    model_name: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    store_ids: Sequence[str] | None = None,
    sku_ids: Sequence[str] | None = None,
    invocation_key: str | None = None,
    scheduled_for: datetime | None = None,
) -> BatchRunResult:
    """
    Typed BatchRunResult entry point (same behavior as run_replenishment_batch).

    INTERNAL / LOW-LEVEL API — production CLI, Admin Run Now, and Render cron
    must call scheduler_service.trigger_replenishment_run() so overlap locks
    and schedule gates apply. Tests may call this directly.
    """
    init_db()
    if trigger_type not in {"scheduled", "manual", "retry"}:
        raise ValueError("trigger_type must be scheduled, manual, or retry")

    now = datetime.now(timezone.utc)
    active_policy = policy_service.ensure_default_policy(created_by=initiated_by)
    effective_policy = policy_version or active_policy.policy_version
    effective_model = model_name if model_name is not None else (OPENAI_MODEL or None)

    with get_session() as session:
        existing = (
            run_repository.get_run(session, run_id) if run_id else None
        )
        if existing is None and invocation_key:
            existing = run_repository.get_run_by_invocation_key(session, invocation_key)
        if existing is not None and existing.status in _TERMINAL_RUN_STATUSES:
            items = run_repository.list_run_items(session, existing.run_id)
            recommendations = run_repository.list_recommendations_for_run(
                session, existing.run_id
            )
            return _batch_result_from_run(
                existing,
                items,
                recommendations,
                errors=[],
                idempotent_replay=True,
            )

        if existing is None:
            pairs = list_eligible_store_sku_pairs(
                store_sku_pairs, store_ids=store_ids, sku_ids=sku_ids
            )
            if not pairs:
                raise ValueError("No store/SKU combinations to score")
            run = ReplenishmentRun(
                run_id=run_id or f"RUN-{uuid4().hex[:12]}",
                started_at=now,
                completed_at=None,
                status="running",
                trigger_type=trigger_type,  # type: ignore[arg-type]
                initiated_by=initiated_by,
                total_items=len(pairs),
                scored_items=0,
                auto_released_items=0,
                review_items=0,
                blocked_items=0,
                no_order_items=0,
                failed_items=0,
                policy_version=effective_policy,
                model_name=effective_model,
                error_summary=None,
                created_at=now,
                invocation_key=invocation_key,
                scheduled_for=scheduled_for,
            )
            run_repository.save_run(session, run)
            for store_id, sku in pairs:
                item = ReplenishmentRunItem(
                    item_id=f"RIT-{uuid4().hex[:12]}",
                    run_id=run.run_id,
                    store_id=store_id,
                    sku=sku,
                    status="pending",
                    disposition=None,
                    recommendation_id=None,
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                )
                run_repository.save_run_item(session, item)
            audit_repository.write_audit_event(
                session,
                "replenishment_run_started",
                actor=initiated_by,
                run_id=run.run_id,
                user_id=user_id,
                session_id=session_id,
                details={
                    "trigger_type": trigger_type,
                    "total_items": run.total_items,
                    "policy_version": effective_policy,
                },
            )
            active_run_id = run.run_id
        else:
            # Resume / retry an existing non-terminal run.
            active_run_id = existing.run_id
            pairs = [
                (item.store_id, item.sku)
                for item in run_repository.list_run_items(session, active_run_id)
            ]
            if store_sku_pairs is not None or store_ids is not None or sku_ids is not None:
                recorded = {
                    (i.store_id, i.sku)
                    for i in run_repository.list_run_items(session, active_run_id)
                }
                for store_id, sku in list_eligible_store_sku_pairs(
                    store_sku_pairs, store_ids=store_ids, sku_ids=sku_ids
                ):
                    if (store_id, sku) in recorded:
                        continue
                    item = ReplenishmentRunItem(
                        item_id=f"RIT-{uuid4().hex[:12]}",
                        run_id=active_run_id,
                        store_id=store_id,
                        sku=sku,
                        status="pending",
                        created_at=now,
                        updated_at=now,
                    )
                    run_repository.save_run_item(session, item)
                    pairs.append((store_id, sku))
            run = existing.model_copy(
                update={
                    "status": "running",
                    "started_at": existing.started_at or now,
                    "trigger_type": trigger_type if trigger_type == "retry" else existing.trigger_type,
                    "policy_version": effective_policy,
                    "model_name": effective_model,
                }
            )
            run.total_items = len(run_repository.list_run_items(session, active_run_id))
            run_repository.save_run(session, run)

    # Process outside the create transaction so each item can commit independently.
    item_errors: list[str] = []
    orders_queued = 0
    for store_id, sku in pairs:
        try:
            queued = _process_run_item(
                run_id=active_run_id,
                store_id=store_id,
                sku=sku,
                initiated_by=initiated_by,
                user_id=user_id,
                session_id=session_id,
            )
            if queued:
                orders_queued += 1
        except Exception as exc:  # noqa: BLE001 — batch isolation
            item_errors.append(f"{store_id}/{sku}: {type(exc).__name__}: {exc}")
            _record_item_failure(
                run_id=active_run_id,
                store_id=store_id,
                sku=sku,
                error_message=f"{type(exc).__name__}: {exc}",
            )

    return _finalize_run(
        active_run_id,
        initiated_by=initiated_by,
        user_id=user_id,
        session_id=session_id,
        extra_errors=item_errors,
        orders_queued=orders_queued,
    )


def _process_run_item(
    *,
    run_id: str,
    store_id: str,
    sku: str,
    initiated_by: str,
    user_id: str | None,
    session_id: str | None,
) -> bool:
    """Score one store/SKU. Returns True when an OrderIntent was newly queued."""
    resume_auto_rec_id: str | None = None
    with get_session() as session:
        existing_item = run_repository.get_run_item(
            session, run_id=run_id, store_id=store_id, sku=sku
        )
        if existing_item is not None and existing_item.status in {"scored", "skipped"}:
            if (
                existing_item.disposition == "auto_release"
                and existing_item.recommendation_id
            ):
                resume_auto_rec_id = existing_item.recommendation_id
            else:
                return False
        else:
            existing_rec = run_repository.get_recommendation_for_run_item(
                session, run_id=run_id, store_id=store_id, sku=sku
            )
            if existing_rec is not None:
                # Idempotent: recommendation already linked to this run item.
                now = datetime.now(timezone.utc)
                if existing_item is None:
                    existing_item = ReplenishmentRunItem(
                        item_id=f"RIT-{uuid4().hex[:12]}",
                        run_id=run_id,
                        store_id=store_id,
                        sku=sku,
                        status="scored",
                        disposition=existing_rec.disposition,
                        recommendation_id=existing_rec.recommendation_id,
                        error_message=None,
                        created_at=now,
                        updated_at=now,
                    )
                else:
                    existing_item = existing_item.model_copy(
                        update={
                            "status": "scored",
                            "disposition": existing_rec.disposition,
                            "recommendation_id": existing_rec.recommendation_id,
                            "error_message": None,
                            "updated_at": now,
                        }
                    )
                run_repository.save_run_item(session, existing_item)
                if existing_rec.disposition == "auto_release":
                    resume_auto_rec_id = existing_rec.recommendation_id
                else:
                    return False
            else:
                existing_rec = None

    if resume_auto_rec_id:
        return _queue_auto_release_order(
            recommendation_id=resume_auto_rec_id,
            actor=initiated_by,
            user_id=user_id,
            session_id=session_id,
        )

    # Score using existing deterministic services (no duplicated formulas).
    product = product_service.get_product_details(sku)
    inventory = inventory_service.get_inventory_position(store_id, sku)
    open_orders = inventory_service.get_open_orders(store_id, sku)
    forecast = forecast_service.get_demand_forecast(store_id, sku)
    replenishment = replenishment_service.calculate_replenishment(
        store_id=store_id,
        sku=sku,
        forecast_units=forecast.forecast_units,
        inventory=inventory,
        product=product,
    )
    risk = risk_service.assess_replenishment_risk(
        days_of_supply=replenishment.days_of_supply,
        recommended_quantity=replenishment.recommended_quantity,
        forecast_units=forecast.forecast_units,
        on_hand=inventory.on_hand,
        usable_on_hand=inventory.usable_on_hand,
        method=forecast.method,
    )
    policy_eval = policy_service.evaluate_replenishment_policy(
        product=product,
        inventory=inventory,
        forecast=forecast,
        replenishment=replenishment,
        risk=risk,
        open_orders=open_orders,
        policy=policy_service.get_active_policy(),
    )
    policy = policy_eval.model_dump(mode="json")
    disposition = str(policy_eval.disposition)
    status = str(
        policy_eval.recommendation_status
        or policy_service.recommendation_status_for_disposition(disposition)
    )
    failed_explanations = [
        rule.explanation
        for rule in policy_eval.evaluated_rules
        if rule.result == "fail"
    ]
    rationale = (
        f"Batch run {run_id}: disposition={disposition}; "
        f"risk={risk.get('risk_level')}; qty={replenishment.recommended_quantity}. "
        + "; ".join(failed_explanations)
    )

    recommendation = recommendation_service.create_recommendation_record(
        store_id,
        sku,
        rationale=rationale,
        forecast_result={
            "forecast_units": float(forecast.forecast_units),
            "average_daily_sales": float(forecast.average_daily_sales),
            "method": forecast.method,
            "forecast_days": int(forecast.forecast_days),
            "generated_at": forecast.generated_at.isoformat(),
        },
        replenishment_result={
            "recommended_quantity": int(replenishment.recommended_quantity),
            "days_of_supply": (
                float(replenishment.days_of_supply)
                if replenishment.days_of_supply is not None
                else None
            ),
            "raw_quantity": float(replenishment.raw_quantity),
            "case_pack": int(replenishment.case_pack),
            "constraints_applied": list(replenishment.constraints_applied),
        },
        risk_result={
            "risk_level": risk.get("risk_level"),
            "reasons": list(risk.get("reasons") or []),
        },
        run_id=run_id,
        actor=initiated_by,
        user_id=user_id,
        session_id=session_id,
        enforce_rate_limit=False,
        disposition=disposition,
        status=status,
        policy_result=policy,
    )

    now = datetime.now(timezone.utc)
    with get_session() as session:
        item = run_repository.get_run_item(
            session, run_id=run_id, store_id=store_id, sku=sku
        )
        if item is None:
            item = ReplenishmentRunItem(
                item_id=f"RIT-{uuid4().hex[:12]}",
                run_id=run_id,
                store_id=store_id,
                sku=sku,
                status="scored",
                disposition=disposition,  # type: ignore[arg-type]
                recommendation_id=recommendation.recommendation_id,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
        else:
            item = item.model_copy(
                update={
                    "status": "scored",
                    "disposition": disposition,
                    "recommendation_id": recommendation.recommendation_id,
                    "error_message": None,
                    "updated_at": now,
                }
            )
        run_repository.save_run_item(session, item)
        correlation_id = audit_service.new_correlation_id()
        policy_version = (
            policy.get("policy_version") if isinstance(policy, dict) else None
        )
        policy_details = {
            "store_id": store_id,
            "sku": sku,
            "disposition": disposition,
            "status": status,
            "recommendation_id": recommendation.recommendation_id,
            "policy_version": policy_version,
        }
        audit_repository.write_audit_event(
            session,
            "replenishment_item_processed",
            actor=initiated_by,
            run_id=run_id,
            recommendation_id=recommendation.recommendation_id,
            store_id=store_id,
            sku=sku,
            correlation_id=correlation_id,
            user_id=user_id,
            session_id=session_id,
            details=policy_details,
        )
        audit_service.record_event(
            audit_service.POLICY_EVALUATED,
            actor="system",
            actor_type=audit_service.ACTOR_TYPE_SYSTEM,
            actor_role="policy_engine",
            run_id=run_id,
            recommendation_id=recommendation.recommendation_id,
            store_id=store_id,
            sku=sku,
            correlation_id=correlation_id,
            user_id=user_id,
            session_id=session_id,
            details=policy_details,
            session=session,
        )
        if disposition == "auto_release":
            audit_service.record_event(
                audit_service.RECOMMENDATION_AUTO_RELEASED,
                actor="system",
                actor_type=audit_service.ACTOR_TYPE_SYSTEM,
                actor_role="policy_engine",
                run_id=run_id,
                recommendation_id=recommendation.recommendation_id,
                store_id=store_id,
                sku=sku,
                correlation_id=correlation_id,
                user_id=user_id,
                session_id=session_id,
                details=policy_details,
                session=session,
            )
        elif disposition == "human_review":
            audit_repository.write_audit_event(
                session,
                "recommendation_routed_to_review",
                actor="system",
                actor_role="policy_engine",
                run_id=run_id,
                recommendation_id=recommendation.recommendation_id,
                store_id=store_id,
                sku=sku,
                correlation_id=correlation_id,
                user_id=user_id,
                session_id=session_id,
                details=policy_details,
            )
        elif disposition == "blocked":
            audit_service.record_event(
                audit_service.RECOMMENDATION_BLOCKED,
                actor="system",
                actor_type=audit_service.ACTOR_TYPE_SYSTEM,
                actor_role="policy_engine",
                run_id=run_id,
                recommendation_id=recommendation.recommendation_id,
                store_id=store_id,
                sku=sku,
                correlation_id=correlation_id,
                user_id=user_id,
                session_id=session_id,
                details={
                    **policy_details,
                    "failed_explanations": failed_explanations[:10],
                },
                session=session,
            )
        elif disposition == "no_order":
            audit_repository.write_audit_event(
                session,
                "recommendation_no_order",
                actor="system",
                actor_role="policy_engine",
                run_id=run_id,
                recommendation_id=recommendation.recommendation_id,
                store_id=store_id,
                sku=sku,
                correlation_id=correlation_id,
                user_id=user_id,
                session_id=session_id,
                details=policy_details,
            )

    if disposition == "auto_release":
        return _queue_auto_release_order(
            recommendation_id=recommendation.recommendation_id,
            actor=initiated_by,
            user_id=user_id,
            session_id=session_id,
        )
    return False


def _queue_auto_release_order(
    *,
    recommendation_id: str,
    actor: str,
    user_id: str | None,
    session_id: str | None,
) -> bool:
    """Queue OrderIntent at pending_erp. Never transmits to ERP. Idempotent."""
    try:
        result = order_lifecycle_service.queue_approved_order(
            recommendation_id=recommendation_id,
            actor=actor or "system",
            actor_role=None,
            user_id=user_id,
            session_id=session_id,
            released_by_type="agent_policy",
            idempotency_key=f"order:auto:{recommendation_id}",
        )
        return result.get("outcome") == "queued"
    except Exception as exc:  # noqa: BLE001 — scoring succeeded; queue is best-effort
        with get_session() as session:
            audit_repository.write_audit_event(
                session,
                "auto_release_order_queue_failed",
                actor=actor or "system",
                recommendation_id=recommendation_id,
                details={"error": f"{type(exc).__name__}: {exc}"[:500]},
            )
        return False


def _record_item_failure(
    *,
    run_id: str,
    store_id: str,
    sku: str,
    error_message: str,
) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        item = run_repository.get_run_item(
            session, run_id=run_id, store_id=store_id, sku=sku
        )
        if item is not None and item.status == "scored":
            return
        if item is None:
            item = ReplenishmentRunItem(
                item_id=f"RIT-{uuid4().hex[:12]}",
                run_id=run_id,
                store_id=store_id,
                sku=sku,
                status="failed",
                disposition=None,
                recommendation_id=None,
                error_message=error_message[:2000],
                created_at=now,
                updated_at=now,
            )
        else:
            item = item.model_copy(
                update={
                    "status": "failed",
                    "disposition": None,
                    "recommendation_id": None,
                    "error_message": error_message[:2000],
                    "updated_at": now,
                }
            )
        run_repository.save_run_item(session, item)
        audit_repository.write_audit_event(
            session,
            "replenishment_run_item_failed",
            actor="system",
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            details={
                "store_id": store_id,
                "sku": sku,
                "error": error_message[:500],
            },
        )


def _finalize_run(
    run_id: str,
    *,
    initiated_by: str,
    user_id: str | None,
    session_id: str | None,
    extra_errors: Iterable[str],
    orders_queued: int = 0,
) -> BatchRunResult:
    now = datetime.now(timezone.utc)
    error_list = list(extra_errors)
    with get_session() as session:
        run = run_repository.get_run(session, run_id)
        if run is None:
            raise ValueError(f"Replenishment run not found: {run_id}")
        items = run_repository.list_run_items(session, run_id)
        scored = [i for i in items if i.status == "scored"]
        failed = [i for i in items if i.status == "failed"]
        auto_released = sum(1 for i in scored if i.disposition == "auto_release")
        review = sum(1 for i in scored if i.disposition == "human_review")
        blocked = sum(1 for i in scored if i.disposition == "blocked")
        no_order = sum(1 for i in scored if i.disposition == "no_order")

        error_bits = [i.error_message for i in failed if i.error_message]
        error_bits.extend(error_list)
        if not scored and failed:
            status = "failed"
        elif failed:
            status = "completed_with_errors"
        else:
            status = "completed"

        updated = run.model_copy(
            update={
                "status": status,
                "completed_at": now,
                "total_items": len(items),
                "scored_items": len(scored),
                "auto_released_items": auto_released,
                "review_items": review,
                "blocked_items": blocked,
                "no_order_items": no_order,
                "failed_items": len(failed),
                "error_summary": "; ".join(error_bits)[:4000] if error_bits else None,
            }
        )
        run_repository.save_run(session, updated)
        details = {
            "status": status,
            "scored_items": len(scored),
            "processed_items": len(scored),
            "auto_released_items": auto_released,
            "review_items": review,
            "human_review_items": review,
            "blocked_items": blocked,
            "no_order_items": no_order,
            "failed_items": len(failed),
            "orders_queued": orders_queued,
        }
        if status == "failed":
            audit_repository.write_audit_event(
                session,
                "replenishment_run_failed",
                actor=initiated_by,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                details=details,
            )
        audit_repository.write_audit_event(
            session,
            "replenishment_run_completed",
            actor=initiated_by,
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            details=details,
        )
        recommendations = run_repository.list_recommendations_for_run(session, run_id)
        return _batch_result_from_run(
            updated,
            items,
            recommendations,
            errors=error_bits,
            idempotent_replay=False,
            orders_queued=orders_queued,
        )


def _batch_result_from_run(
    run: ReplenishmentRun,
    items: list[ReplenishmentRunItem],
    recommendations: list[Any],
    *,
    errors: list[str],
    idempotent_replay: bool,
    orders_queued: int = 0,
) -> BatchRunResult:
    no_order = int(getattr(run, "no_order_items", 0) or 0)
    if no_order == 0:
        no_order = sum(1 for i in items if i.disposition == "no_order")
    return BatchRunResult(
        run_id=run.run_id,
        status=run.status,  # type: ignore[arg-type]
        trigger_type=run.trigger_type,  # type: ignore[arg-type]
        initiated_by=run.initiated_by,
        total_items=run.total_items,
        scored_items=run.scored_items,
        processed_items=run.scored_items,
        auto_released_items=run.auto_released_items,
        review_items=run.review_items,
        human_review_items=run.review_items,
        blocked_items=run.blocked_items,
        no_order_items=no_order,
        failed_items=run.failed_items,
        policy_version=run.policy_version,
        model_name=run.model_name,
        agent_model=run.model_name,
        error_summary=run.error_summary,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        created_at=run.created_at.isoformat(),
        errors=list(errors),
        items=[item.model_dump(mode="json") for item in items],
        recommendation_ids=[row.recommendation_id for row in recommendations],
        recommendations=[
            {
                "recommendation_id": row.recommendation_id,
                "store_id": row.store_id,
                "sku": row.sku,
                "run_id": row.run_id,
                "disposition": row.disposition,
                "status": row.status,
                "agent_recommended_quantity": row.agent_recommended_quantity,
                "risk_level": row.risk_level,
            }
            for row in recommendations
        ],
        idempotent_replay=idempotent_replay,
        orders_queued=orders_queued,
    )

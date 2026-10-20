"""Purchase orders and ERP cutoff transmission (via outbox + adapter)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database.connection import get_session, init_db
from models.erp_outbox import ErpOutboxEntry
from models.purchase_order import PurchaseOrder
from repositories import (
    approval_repository,
    audit_repository,
    erp_outbox_repository,
    order_intent_repository,
    purchase_order_repository,
)
from services import auth_service, erp_service, queue_service

STATUS_DRAFT = "queued_for_erp"
STATUS_QUEUED = "queued_for_erp"
STATUS_SENT = "completed"
STATUS_FAILED = "transmission_failed"

_AUTO_APPROVAL_PREFIX = "AUTO-"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _outbox_payload(po: PurchaseOrder) -> dict[str, Any]:
    return {
        "purchase_order_id": po.purchase_order_id,
        "approval_id": po.approval_id,
        "recommendation_id": po.recommendation_id,
        "store_id": po.store_id,
        "sku": po.sku,
        "agent_recommended_quantity": po.agent_recommended_quantity,
        "human_proposed_quantity": po.human_proposed_quantity,
        "approved_final_quantity": po.approved_final_quantity,
        "override_used": po.override_used,
        "override_reason": po.override_reason,
        "vendor": po.vendor,
        "amount": po.amount,
        "lines": po.lines,
        "unit_cost": (po.lines[0].get("unit_cost") if po.lines else None),
    }


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
    Create an idempotent purchase order (pending_erp) from a verified approval.

    Queues an OrderIntent — does not transmit. Never accepts model-invented qty.
    """
    from services import order_lifecycle_service

    result = order_lifecycle_service.queue_approved_order(
        approval_id=approval_id,
        actor=actor,
        actor_role=actor_role,
        user_id=user_id,
        session_id=session_id,
        idempotency_key=(
            f"order:{approval_id}"
            if idempotency_key is None
            else idempotency_key.replace("po:", "order:", 1)
            if idempotency_key.startswith("po:")
            else idempotency_key
        ),
        released_by_type="human",
    )
    po_payload = result.get("purchase_order")
    if not po_payload:
        raise ValueError("Failed to queue approved order")
    return PurchaseOrder.model_validate(po_payload)


def create_purchase_order_from_auto_release(
    recommendation_id: str,
    *,
    actor: str = "system",
    actor_role: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> PurchaseOrder:
    """Create a pending_erp PO for an auto-released recommendation (no human approval)."""
    from services import order_lifecycle_service

    result = order_lifecycle_service.queue_approved_order(
        recommendation_id=recommendation_id,
        actor=actor,
        actor_role=actor_role,
        user_id=user_id,
        session_id=session_id,
        released_by_type="agent_policy",
    )
    po_payload = result.get("purchase_order")
    if not po_payload:
        raise ValueError("Failed to queue auto-released order")
    return PurchaseOrder.model_validate(po_payload)


def get_purchase_order_status(purchase_order_id: str) -> dict[str, Any]:
    with get_session() as session:
        po = purchase_order_repository.get_purchase_order(session, purchase_order_id)
    if po is None:
        return {"purchase_order_id": purchase_order_id, "status": "not_found"}
    return po.model_dump(mode="json")


def save_delivery_invoice(purchase_order_id: str, invoice_number: str) -> dict[str, Any]:
    """Persist invoice number on the order intent payload for a purchase order."""
    from datetime import datetime, timezone

    po_id = str(purchase_order_id or "").strip()
    invoice = str(invoice_number or "").strip()
    if not po_id:
        return {"ok": False, "message": "Purchase order is required."}
    if not invoice:
        return {"ok": False, "message": "Enter an invoice number before saving."}

    init_db()
    with get_session() as session:
        po = purchase_order_repository.get_purchase_order(session, po_id)
        if po is None:
            return {"ok": False, "message": "Purchase order not found."}
        intent = order_intent_repository.get_by_purchase_order(session, po_id)
        if intent is None and po.recommendation_id:
            intent = order_intent_repository.get_by_recommendation(
                session, po.recommendation_id
            )
        if intent is None:
            return {
                "ok": False,
                "message": "No order record is available to store an invoice number.",
            }
        payload = dict(intent.payload or {})
        payload["invoice_number"] = invoice
        updated = intent.model_copy(
            update={
                "payload": payload,
                "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
            }
        )
        order_intent_repository.save_order_intent(session, updated)
    return {"ok": True, "purchase_order_id": po_id, "invoice_number": invoice}


def list_purchase_orders(
    *,
    transmission_status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    init_db()
    with get_session() as session:
        rows = purchase_order_repository.list_purchase_orders(
            session, transmission_status=transmission_status, limit=limit
        )
    return [po.model_dump(mode="json") for po in rows]


def enqueue_purchase_order(
    purchase_order_id: str,
    *,
    actor: str = "system",
    actor_role: str | None = None,
    run_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Place a draft/failed PO onto the ERP outbox (idempotent if already queued/sent)."""
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_create_purchase_order(actor_role),
            "enqueue a purchase order for ERP",
        )
    init_db()
    with get_session() as session:
        po = purchase_order_repository.get_purchase_order(session, purchase_order_id)
        if po is None:
            raise ValueError(f"Purchase order not found: {purchase_order_id}")
        if po.transmission_status == "sent":
            existing = erp_outbox_repository.get_outbox_by_purchase_order(
                session, purchase_order_id
            )
            return {
                "purchase_order_id": purchase_order_id,
                "outcome": "already_sent",
                "outbox_id": existing.outbox_id if existing else None,
                "transmission_status": po.transmission_status,
            }

        existing = erp_outbox_repository.get_outbox_by_purchase_order(session, purchase_order_id)
        now = _now()
        if existing is not None and existing.status == "pending":
            return {
                "purchase_order_id": purchase_order_id,
                "outcome": "already_queued",
                "outbox_id": existing.outbox_id,
                "transmission_status": po.transmission_status,
            }

        if existing is None:
            entry = ErpOutboxEntry(
                outbox_id=f"OUT-{uuid4().hex[:12]}",
                purchase_order_id=purchase_order_id,
                run_id=run_id,
                batch_id=batch_id,
                payload=_outbox_payload(po),
                status="pending",
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        else:
            # Retry after failure — reset to pending with same outbox id.
            entry = existing.model_copy(
                update={
                    "status": "pending",
                    "batch_id": batch_id or existing.batch_id,
                    "run_id": run_id or existing.run_id,
                    "payload": _outbox_payload(po),
                    "last_error": None,
                    "updated_at": now,
                }
            )
        erp_outbox_repository.save_outbox(session, entry)
        po.status = STATUS_QUEUED
        po.order_status = "queued_for_erp"
        po.transmission_status = "queued"
        po.transmission_error = None
        purchase_order_repository.update_purchase_order(session, po)
        audit_repository.write_audit_event(
            session,
            "erp_outbox_enqueued",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=po.recommendation_id,
            approval_id=po.approval_id,
            purchase_order_id=po.purchase_order_id,
            details={"outbox_id": entry.outbox_id, "batch_id": batch_id},
        )
        return {
            "purchase_order_id": purchase_order_id,
            "outcome": "queued",
            "outbox_id": entry.outbox_id,
            "transmission_status": "queued",
        }


def process_erp_outbox(
    *,
    actor: str = "system",
    actor_role: str | None = None,
    batch_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Transmit pending outbox entries through the configured ERP adapter."""
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_create_purchase_order(actor_role),
            "send purchase orders to ERP",
        )
    init_db()
    with get_session() as session:
        pending = erp_outbox_repository.list_outbox(
            session, status="pending", batch_id=batch_id, limit=limit
        )

    sent = failed = 0
    results: list[dict[str, Any]] = []
    for entry in pending:
        outcome = _transmit_one(entry, actor=actor, actor_role=actor_role)
        results.append(outcome)
        if outcome["outcome"] == "sent":
            sent += 1
        else:
            failed += 1

    return {
        "attempted": len(pending),
        "sent": sent,
        "failed": failed,
        "batch_id": batch_id,
        "adapter": erp_service.adapter_health().get("adapter"),
        "results": results,
    }


def _transmit_one(
    entry: ErpOutboxEntry,
    *,
    actor: str,
    actor_role: str | None,
) -> dict[str, Any]:
    """Delegate outbox drain to the single OrderIntent transmission entry point."""
    from services import order_lifecycle_service

    result = order_lifecycle_service.transmit_order_intent(
        purchase_order_id=entry.purchase_order_id,
        actor=actor,
        actor_role=actor_role,
    )
    now = _now()
    with get_session() as session:
        current = erp_outbox_repository.get_outbox(session, entry.outbox_id)
        if current is None:
            return {
                "outbox_id": entry.outbox_id,
                "purchase_order_id": entry.purchase_order_id,
                "outcome": "failed",
                "error": "Outbox missing",
            }
        attempts = current.attempts + 1
        outcome = result.get("outcome")
        if outcome in {"transmitted", "already_transmitted"}:
            updated = current.model_copy(
                update={
                    "status": "sent",
                    "attempts": attempts,
                    "erp_reference": result.get("external_order_id"),
                    "last_error": None,
                    "sent_at": now,
                    "updated_at": now,
                }
            )
            erp_outbox_repository.save_outbox(session, updated)
            return {
                "outbox_id": entry.outbox_id,
                "purchase_order_id": entry.purchase_order_id,
                "outcome": "sent",
                "erp_reference": result.get("external_order_id"),
            }
        error = result.get("error") or "ERP transmission failed"
        updated = current.model_copy(
            update={
                "status": "failed",
                "attempts": attempts,
                "last_error": error,
                "updated_at": now,
            }
        )
        erp_outbox_repository.save_outbox(session, updated)
        return {
            "outbox_id": entry.outbox_id,
            "purchase_order_id": entry.purchase_order_id,
            "outcome": "failed",
            "error": error,
        }


def send_approved_to_erp(
    *,
    actor: str,
    actor_role: str,
    run_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Cutoff batch: ensure POs for Approved Today, enqueue drafts, transmit via mock ERP.

    Idempotent for already-sent orders. Does not invent quantities.
    """
    auth_service.require_permission(
        actor_role,
        auth_service.can_create_purchase_order(actor_role),
        "send approved orders to ERP",
    )
    init_db()
    approved = queue_service.get_approved_today(run_id=run_id)
    batch_id = f"CUTOFF-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    active_run_id = (approved.get("run") or {}).get("run_id") or run_id

    prepared: list[dict[str, Any]] = []
    created = queued = skipped = prep_failed = 0

    for row in approved["rows"]:
        rec_id = row["recommendation_id"]
        try:
            with get_session() as session:
                po = purchase_order_repository.get_purchase_order_by_recommendation(
                    session, rec_id
                )
            if po is None and row["source"] == "Human approved":
                approval = None
                with get_session() as session:
                    approval = approval_repository.get_latest_approval_for_recommendation(
                        session, rec_id
                    )
                if approval is None or approval.status != "approved":
                    raise ValueError("Human-approved item has no approved approval record")
                po = create_mock_purchase_order(
                    approval.approval_id,
                    actor=actor,
                    actor_role=actor_role,
                    user_id=user_id or actor,
                    session_id=session_id,
                )
                created += 1
            elif po is None and row["source"] == "Auto-released":
                po = create_purchase_order_from_auto_release(
                    rec_id,
                    actor=actor,
                    actor_role=actor_role,
                    user_id=user_id or actor,
                    session_id=session_id,
                )
                created += 1
            elif po is None:
                raise ValueError(f"Unsupported approved source: {row['source']}")

            if po.transmission_status == "sent":
                skipped += 1
                prepared.append(
                    {
                        "recommendation_id": rec_id,
                        "purchase_order_id": po.purchase_order_id,
                        "outcome": "already_sent",
                    }
                )
                continue

            enq = enqueue_purchase_order(
                po.purchase_order_id,
                actor=actor,
                actor_role=actor_role,
                run_id=active_run_id,
                batch_id=batch_id,
            )
            if enq["outcome"] in {"queued", "already_queued"}:
                queued += 1
            prepared.append(
                {
                    "recommendation_id": rec_id,
                    "purchase_order_id": po.purchase_order_id,
                    **enq,
                }
            )
        except Exception as exc:  # noqa: BLE001 — cutoff continues per item
            prep_failed += 1
            prepared.append(
                {
                    "recommendation_id": rec_id,
                    "outcome": "failed",
                    "error": str(exc),
                }
            )

    transmit = process_erp_outbox(
        actor=actor,
        actor_role=actor_role,
        batch_id=batch_id,
    )

    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "erp_cutoff_batch",
            actor=actor,
            actor_role=actor_role,
            details={
                "batch_id": batch_id,
                "run_id": active_run_id,
                "created": created,
                "queued": queued,
                "skipped": skipped,
                "prep_failed": prep_failed,
                "sent": transmit["sent"],
                "failed": transmit["failed"],
            },
        )

    return {
        "batch_id": batch_id,
        "run_id": active_run_id,
        "approved_items": approved["summary"]["total"],
        "purchase_orders_created": created,
        "enqueued": queued,
        "already_sent_skipped": skipped,
        "prepare_failed": prep_failed,
        "transmitted": transmit["sent"],
        "transmission_failed": transmit["failed"],
        "adapter": transmit.get("adapter"),
        "prepared": prepared,
        "transmit": transmit,
    }


def get_orders_workbench(*, limit: int = 100) -> dict[str, Any]:
    """Read model for the Orders / Purchase Orders page."""
    init_db()
    orders = list_purchase_orders(limit=limit)
    # Enrich with released-by labels for display.
    from services.order_lifecycle_service import (
        format_released_by_label,
        display_name_for_user,
    )

    enriched: list[dict[str, Any]] = []
    with get_session() as session:
        for o in orders:
            intent = None
            if o.get("recommendation_id"):
                intent = order_intent_repository.get_by_recommendation(
                    session, o["recommendation_id"]
                )
            released_type = (
                intent.released_by_type if intent else (
                    "agent_policy"
                    if str(o.get("approval_id") or "").startswith(_AUTO_APPROVAL_PREFIX)
                    else "human"
                )
            )
            approved_by = (intent.approved_by if intent else None) or o.get("approved_by")
            row = {
                **o,
                "lines_count": len(o.get("lines") or []),
                "value": o.get("amount"),
                "order_status": o.get("order_status") or o.get("status") or "queued_for_erp",
                "order_status_label": None,
                "erp_status": o.get("order_status") or o.get("status") or "queued_for_erp",
                "erp_provider": o.get("erp_provider")
                or (intent.erp_provider if intent else None)
                or "Mock ERP",
                "attempt_count": o.get("attempt_count")
                if o.get("attempt_count") is not None
                else (intent.attempts if intent else 0),
                "external_order_id": o.get("external_order_id")
                or o.get("erp_reference")
                or (intent.external_order_id if intent else None)
                or (intent.mock_erp_reference if intent else None),
                "acknowledged_at": o.get("acknowledged_at")
                or (intent.acknowledged_at.isoformat() if intent and intent.acknowledged_at else None),
                "last_failure": o.get("transmission_error")
                or o.get("last_error_code")
                or (intent.last_error_message if intent else None)
                or (intent.last_error if intent else None),
                "source_run_id": o.get("source_run_id")
                or (intent.source_run_id if intent else None),
                "order_intent_id": intent.order_intent_id if intent else None,
                "approved_by_display": (
                    intent.released_by_label
                    if intent and intent.released_by_label
                    else format_released_by_label(
                        released_by_type=released_type, approved_by=approved_by
                    )
                ),
                "approved_by_user": display_name_for_user(approved_by)
                if released_type == "human"
                else approved_by,
            }
            from services.queue_service import format_order_status_label

            row["order_status_label"] = format_order_status_label(row["order_status"])
            row["erp_status_label"] = format_order_status_label(row["erp_status"])
            next_retry = o.get("next_retry_at") or (
                intent.next_retry_at.isoformat()
                if intent and getattr(intent, "next_retry_at", None)
                else None
            )
            row["next_retry_at"] = next_retry
            retry_display = None
            if next_retry:
                try:
                    parsed = datetime.fromisoformat(str(next_retry).replace("Z", "+00:00"))
                    retry_display = parsed.strftime("%I:%M %p").lstrip("0")
                except ValueError:
                    retry_display = str(next_retry)[:16]
            from config import ERP_AUTO_TRANSMIT
            from services import order_lifecycle_states as ols

            row["next_step"] = ols.next_step_label(
                row["order_status"], auto_transmit=ERP_AUTO_TRANSMIT
            )
            row["failure"] = ols.failure_guidance(
                row["order_status"],
                last_failure=row.get("last_failure"),
                retry_at_display=retry_display,
            )
            row["vendor"] = o.get("vendor") or "—"
            row["items_count"] = row["lines_count"] or (
                1 if o.get("sku") else 0
            )
            submitted = o.get("transmitted_at") or row.get("acknowledged_at")
            if isinstance(submitted, str) and "T" in submitted:
                submitted_display = submitted.replace("T", " ")[:16]
            elif submitted:
                submitted_display = str(submitted)[:16]
            else:
                submitted_display = "—"
            row["expected_or_submitted"] = submitted_display
            enriched.append(row)
        pending_outbox = erp_outbox_repository.list_outbox(session, status="pending", limit=limit)
        failed_outbox = erp_outbox_repository.list_outbox(session, status="failed", limit=limit)

    from config import ERP_AUTO_TRANSMIT
    from services import order_lifecycle_states as ols

    def _count(*statuses: str) -> int:
        wanted = {ols.normalize_status(s) for s in statuses}
        return sum(
            1
            for o in enriched
            if ols.normalize_status(o.get("order_status")) in wanted
        )

    ready = _count(ols.QUEUED_FOR_ERP)
    sending = _count(ols.TRANSMITTING)
    accepted = _count(ols.COMPLETED, ols.ERP_ACKNOWLEDGED)
    attention = _count(
        ols.TRANSMISSION_FAILED, ols.RETRY_PENDING, ols.ERP_REJECTED
    )
    total_value = sum(float(o.get("value") or o.get("amount") or 0) for o in enriched)
    ready_value = sum(
        float(o.get("value") or o.get("amount") or 0)
        for o in enriched
        if ols.normalize_status(o.get("order_status")) == ols.QUEUED_FOR_ERP
    )

    summary = {
        "total": len(enriched),
        "draft": sum(1 for o in enriched if o.get("transmission_status") == "draft"),
        "queued": ready,
        "sent": accepted,
        "failed": attention,
        "pending_erp": ready,
        "queued_for_erp": ready,
        "transmitting": sending,
        "transmitted": accepted,
        "completed": _count(ols.COMPLETED),
        "retry_pending": _count(ols.RETRY_PENDING),
        "erp_rejected": _count(ols.ERP_REJECTED),
        "ready_to_send": ready,
        "sending": sending,
        "accepted": accepted,
        "attention_needed": attention,
        "total_value": total_value,
        "ready_value": ready_value,
        "total_value_display": f"${total_value:,.2f}",
        "ready_value_display": f"${ready_value:,.2f}",
        "auto_transmit": ERP_AUTO_TRANSMIT,
    }
    adapter = erp_service.adapter_health()
    adapter_key = str(adapter.get("adapter") or "mock").lower()
    purchasing_connection = (
        "Demo system" if adapter_key in {"mock", "demo"} else adapter_key
    )
    if ERP_AUTO_TRANSMIT:
        story = (
            "The agent prepares approved orders and sends them according to "
            "the configured purchasing schedule."
        )
        if ready:
            subtitle = (
                f"{ready} approved order{'s' if ready != 1 else ''} totaling "
                f"{summary['ready_value_display']} "
                f"{'are' if ready != 1 else 'is'} ready for the next purchasing cycle."
            )
        else:
            subtitle = "No orders are waiting for the next purchasing cycle."
    else:
        story = (
            "The agent prepares approved orders. This demo environment does not "
            "run a production purchasing schedule — authorized users can send now."
        )
        if ready:
            subtitle = (
                f"{ready} approved order{'s' if ready != 1 else ''} totaling "
                f"{summary['ready_value_display']} "
                f"{'are' if ready != 1 else 'is'} ready to send."
            )
        else:
            subtitle = "No purchase orders are ready to send."

    return {
        "summary": summary,
        "orders": enriched,
        "outbox_pending": len(pending_outbox),
        "outbox_failed": len(failed_outbox),
        "adapter": adapter,
        "purchasing_connection": purchasing_connection,
        "story": story,
        "subtitle": subtitle,
    }

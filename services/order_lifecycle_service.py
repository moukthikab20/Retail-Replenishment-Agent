"""Order lifecycle: OrderIntent queue + ERP transmission with idempotency.

After approval, orders enter queued_for_erp. They are never acknowledged
until transmit_order_intent / transmit_order_to_erp succeeds.
QUEUE ≠ TRANSMIT — approval and auto-release only enqueue.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from config import (
    DEMO_USERS,
    ERP_MAX_RETRY_ATTEMPTS,
    ERP_RETRY_DELAY_SECONDS,
)
from database.connection import get_session, init_db
from models.erp_outbox import (
    ERP_OUTCOME_ACCEPTED,
    ERP_OUTCOME_REJECTED,
    ERPTransmissionResult,
)
from models.order_intent import OrderIntent, OrderLine
from models.purchase_order import PurchaseOrder
from repositories import (
    approval_repository,
    audit_repository,
    human_review_repository,
    order_intent_repository,
    purchase_order_repository,
    recommendation_repository,
    run_repository,
)
from services import auth_service, erp_service, product_service
from services import order_lifecycle_states as ols
from integrations.demo_supplier import DEFAULT_VENDOR_NAME
from integrations.factory import get_supplier_provider

# Backward-compatible alias for tests/callers expecting a constant.
DEFAULT_VENDOR = DEFAULT_VENDOR_NAME
RELEASED_BY_AGENT = "Agent — Within Policy"

ORDER_QUEUED_FOR_ERP = ols.QUEUED_FOR_ERP
ORDER_PENDING_ERP = ols.QUEUED_FOR_ERP  # legacy alias → queued_for_erp
ORDER_TRANSMITTING = ols.TRANSMITTING
ORDER_ERP_ACKNOWLEDGED = ols.ERP_ACKNOWLEDGED
ORDER_COMPLETED = ols.COMPLETED
ORDER_TRANSMISSION_FAILED = ols.TRANSMISSION_FAILED
ORDER_RETRY_PENDING = ols.RETRY_PENDING
ORDER_ERP_REJECTED = ols.ERP_REJECTED
ORDER_CANCELLED = ols.CANCELLED
# Legacy names kept for older imports/tests
ORDER_TRANSMITTED = ols.COMPLETED
ORDER_ACKNOWLEDGED = ols.ERP_ACKNOWLEDGED
ORDER_IN_TRANSIT = ols.IN_TRANSIT
ORDER_RECEIVED = ols.RECEIVED
ORDER_FAILED = ols.TRANSMISSION_FAILED

_AUTO_APPROVAL_PREFIX = "AUTO-"
_TERMINAL_TRANSMITTED = ols.TERMINAL_SUCCESS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _po_id() -> str:
    return f"PO-MOCK-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"


def _intent_id() -> str:
    return f"OI-{uuid4().hex[:12].upper()}"


def display_name_for_user(user_id: str | None) -> str:
    if not user_id:
        return "—"
    meta = DEMO_USERS.get(user_id) or {}
    return str(meta.get("display_name") or user_id)


def format_released_by_label(*, released_by_type: str, approved_by: str | None) -> str:
    if released_by_type == "agent_policy":
        return RELEASED_BY_AGENT
    return display_name_for_user(approved_by)


def _default_vendor_name() -> str:
    return get_supplier_provider().get_default_vendor().vendor_name


def _vendor_name_for_sku(sku: str) -> str:
    try:
        product = product_service.get_product_details(sku)
    except ValueError:
        return _default_vendor_name()
    vendor_id = getattr(product, "vendor_id", None)
    if vendor_id:
        supplier = get_supplier_provider().get_supplier(str(vendor_id))
        if supplier is not None:
            return supplier.vendor_name
    return _default_vendor_name()


def _unit_cost(sku: str) -> float:
    try:
        product = product_service.get_product_details(sku)
    except ValueError:
        return 0.0
    try:
        return float(product.unit_cost)
    except (TypeError, ValueError):
        return 0.0


def _build_lines(
    *,
    store_id: str,
    sku: str,
    product_name: str | None,
    quantity: int,
    unit_cost: float,
) -> list[OrderLine]:
    amount = round(unit_cost * quantity, 2)
    return [
        OrderLine(
            line_number=1,
            sku=sku,
            store_id=store_id,
            product_name=product_name,
            quantity=quantity,
            unit_cost=unit_cost,
            line_amount=amount,
        )
    ]


def _source_run_id(session, recommendation_id: str) -> str | None:
    row = recommendation_repository.get_recommendation_row(session, recommendation_id)
    if row is not None and getattr(row, "run_id", None):
        return row.run_id
    run = run_repository.get_latest_run(session, terminal_only=False)
    return run.run_id if run else None


def queue_approved_order(
    *,
    approval_id: str | None = None,
    recommendation_id: str | None = None,
    actor: str = "system",
    actor_role: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    released_by_type: str | None = None,
    released_by_label: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """
    Create an OrderIntent (+ linked PurchaseOrder) in queued_for_erp.

    Idempotent on approval_id / recommendation_id / idempotency_key.
    Does NOT transmit to ERP (QUEUE ≠ TRANSMIT).
    """
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_create_purchase_order(actor_role),
            "queue an approved order",
        )
    if not approval_id and not recommendation_id:
        raise ValueError("approval_id or recommendation_id is required")

    init_db()
    with get_session() as session:
        # Resolve identity + quantities from approval or auto-release recommendation.
        override_used = False
        override_reason: str | None = None
        synthetic = False

        if approval_id and not approval_id.startswith(_AUTO_APPROVAL_PREFIX):
            existing_intent = order_intent_repository.get_by_approval(session, approval_id)
            if existing_intent is not None:
                po = (
                    purchase_order_repository.get_purchase_order(
                        session, existing_intent.purchase_order_id
                    )
                    if existing_intent.purchase_order_id
                    else purchase_order_repository.get_purchase_order_by_approval(
                        session, approval_id
                    )
                )
                return _queued_payload(existing_intent, po, outcome="already_queued")

            existing_po = purchase_order_repository.get_purchase_order_by_approval(
                session, approval_id
            )
            if existing_po is not None:
                intent = order_intent_repository.get_by_recommendation(
                    session, existing_po.recommendation_id or ""
                )
                if intent is not None:
                    return _queued_payload(intent, existing_po, outcome="already_queued")

            approval = approval_repository.get_approval(session, approval_id)
            if approval is None:
                raise ValueError(f"Approval not found: {approval_id}")
            if approval.status != "approved":
                raise ValueError(
                    f"Cannot queue order; approval status is {approval.status}"
                )
            if approval.approved_final_quantity is None:
                raise ValueError("approved_final_quantity is required")
            recommendation_id = approval.recommendation_id
            recommendation = recommendation_repository.get_recommendation(
                session, recommendation_id
            )
            rec_row = recommendation_repository.get_recommendation_row(
                session, recommendation_id
            )
            if recommendation is None or rec_row is None:
                raise ValueError("Recommendation missing for approval")
            review = human_review_repository.get_human_review(session, approval.review_id)
            if review is None:
                raise ValueError("Review missing for approval")
            qty = int(approval.approved_final_quantity)
            agent_qty = int(approval.agent_recommended_quantity)
            human_qty = int(approval.human_proposed_quantity)
            override_used = bool(review.override_used)
            override_reason = review.override_reason
            approved_by = approval.approved_by or actor
            key = idempotency_key or f"order:{approval_id}"
            by_type = released_by_type or "human"
            user_id = user_id or approval.user_id
            session_id = session_id or approval.session_id
            product_name = rec_row.product_name or None
        else:
            # Auto-release path (synthetic approval id or recommendation only).
            if recommendation_id is None and approval_id:
                recommendation_id = approval_id.removeprefix(_AUTO_APPROVAL_PREFIX)
            assert recommendation_id is not None
            existing_intent = order_intent_repository.get_by_recommendation(
                session, recommendation_id
            )
            if existing_intent is not None:
                po = (
                    purchase_order_repository.get_purchase_order(
                        session, existing_intent.purchase_order_id
                    )
                    if existing_intent.purchase_order_id
                    else purchase_order_repository.get_purchase_order_by_recommendation(
                        session, recommendation_id
                    )
                )
                return _queued_payload(existing_intent, po, outcome="already_queued")

            existing_po = purchase_order_repository.get_purchase_order_by_recommendation(
                session, recommendation_id
            )
            if existing_po is not None:
                intent = order_intent_repository.get_by_recommendation(
                    session, recommendation_id
                )
                if intent is not None:
                    return _queued_payload(intent, existing_po, outcome="already_queued")

            rec_row = recommendation_repository.get_recommendation_row(
                session, recommendation_id
            )
            recommendation = recommendation_repository.get_recommendation(
                session, recommendation_id
            )
            if rec_row is None or recommendation is None:
                raise ValueError(f"Recommendation not found: {recommendation_id}")
            if (rec_row.disposition or "") != "auto_release" and approval_id is None:
                raise ValueError(
                    "recommendation_id without approval_id is only valid for auto_release"
                )
            qty = int(recommendation.agent_recommended_quantity or 0)
            if qty < 0:
                raise ValueError("Invalid quantity for order")
            agent_qty = qty
            human_qty = qty
            approval_id = approval_id or f"{_AUTO_APPROVAL_PREFIX}{recommendation_id}"
            approved_by = actor
            key = idempotency_key or f"order:auto:{recommendation_id}"
            by_type = released_by_type or "agent_policy"
            synthetic = True
            user_id = user_id or rec_row.user_id
            session_id = session_id or rec_row.session_id
            product_name = rec_row.product_name or None

        by_key = order_intent_repository.get_by_idempotency_key(session, key)
        if by_key is not None:
            po = (
                purchase_order_repository.get_purchase_order(session, by_key.purchase_order_id)
                if by_key.purchase_order_id
                else None
            )
            return _queued_payload(by_key, po, outcome="already_queued")

        po_key = f"po:{approval_id}" if not synthetic else f"po:auto:{recommendation_id}"
        existing_po_key = purchase_order_repository.get_purchase_order_by_idempotency_key(
            session, po_key
        )
        if existing_po_key is not None:
            # Attach intent to existing PO (legacy path) without creating a second PO.
            intent = _intent_from_po(
                existing_po_key,
                key=key,
                released_by_type=by_type,
                released_by_label=released_by_label
                or format_released_by_label(
                    released_by_type=by_type, approved_by=approved_by
                ),
                product_name=product_name or existing_po_key.sku,
            )
            saved_intent = order_intent_repository.save_order_intent(session, intent)
            return _queued_payload(saved_intent, existing_po_key, outcome="already_queued")

        unit_cost = _unit_cost(recommendation.sku)
        lines = _build_lines(
            store_id=recommendation.store_id,
            sku=recommendation.sku,
            product_name=product_name,
            quantity=qty,
            unit_cost=unit_cost,
        )
        amount = lines[0].line_amount
        label = released_by_label or format_released_by_label(
            released_by_type=by_type, approved_by=approved_by
        )
        source_run = _source_run_id(session, recommendation_id)
        now = _now()
        po_id = _po_id()
        intent_id = _intent_id()

        po = PurchaseOrder(
            purchase_order_id=po_id,
            approval_id=approval_id,
            recommendation_id=recommendation_id,
            store_id=recommendation.store_id,
            sku=recommendation.sku,
            agent_recommended_quantity=agent_qty,
            human_proposed_quantity=human_qty,
            approved_final_quantity=qty,
            override_used=override_used,
            override_reason=override_reason,
            status=ORDER_QUEUED_FOR_ERP,
            order_status=ORDER_QUEUED_FOR_ERP,
            transmission_status="draft",
            vendor=_vendor_name_for_sku(recommendation.sku),
            amount=amount,
            lines=[line.model_dump(mode="json") for line in lines],
            source_run_id=source_run,
            approved_by=approved_by,
            created_at=now,
            idempotency_key=po_key,
            transmission_idempotency_key=ols.transmission_idempotency_key(intent_id),
            user_id=user_id,
            session_id=session_id,
        )
        tx_key = ols.transmission_idempotency_key(intent_id)
        intent = OrderIntent(
            order_intent_id=intent_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            purchase_order_id=po_id,
            status=ORDER_QUEUED_FOR_ERP,
            store_id=recommendation.store_id,
            sku=recommendation.sku,
            product_name=product_name,
            quantity=qty,
            unit_cost=unit_cost,
            amount=amount,
            vendor=_vendor_name_for_sku(recommendation.sku),
            lines=lines,
            source_run_id=source_run,
            approved_by=approved_by,
            released_by_type=by_type,  # type: ignore[arg-type]
            released_by_label=label,
            idempotency_key=key,
            transmission_idempotency_key=tx_key,
            created_at=now,
            updated_at=now,
            user_id=user_id,
            session_id=session_id,
            payload={
                "purchase_order_id": po_id,
                "approval_id": approval_id,
                "recommendation_id": recommendation_id,
                "store_id": recommendation.store_id,
                "sku": recommendation.sku,
                "approved_final_quantity": qty,
                "quantity": qty,
                "vendor": _vendor_name_for_sku(recommendation.sku),
                "unit_cost": unit_cost,
                "amount": amount,
                "lines": [line.model_dump(mode="json") for line in lines],
                "transmission_idempotency_key": tx_key,
            },
        )
        try:
            saved_po = purchase_order_repository.save_purchase_order(session, po)
            # If a race returned an existing PO, align intent to that PO id.
            if saved_po.purchase_order_id != po_id:
                intent = intent.model_copy(
                    update={
                        "purchase_order_id": saved_po.purchase_order_id,
                        "payload": {
                            **intent.payload,
                            "purchase_order_id": saved_po.purchase_order_id,
                        },
                    }
                )
            saved_intent = order_intent_repository.save_order_intent(session, intent)
            # Auto-release remains recallable until ERP transmit; human path is approved.
            next_status = "approved" if by_type == "human" else "auto_released"
            recommendation_repository.update_recommendation_status(
                session, recommendation_id, next_status
            )
            audit_repository.write_audit_event(
                session,
                "order_intent_queued",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=recommendation_id,
                approval_id=approval_id,
                purchase_order_id=saved_po.purchase_order_id,
                store_id=recommendation.store_id,
                sku=recommendation.sku,
                user_id=user_id,
                session_id=session_id,
                details={
                    "order_intent_id": saved_intent.order_intent_id,
                    "status": ORDER_QUEUED_FOR_ERP,
                    "idempotency_key": key,
                    "transmission_idempotency_key": tx_key,
                    "released_by_type": by_type,
                    "released_by_label": label,
                    "store_id": recommendation.store_id,
                    "sku": recommendation.sku,
                },
            )
            audit_repository.write_audit_event(
                session,
                "purchase_order_created",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=recommendation_id,
                approval_id=approval_id,
                purchase_order_id=saved_po.purchase_order_id,
                store_id=recommendation.store_id,
                sku=recommendation.sku,
                user_id=user_id,
                session_id=session_id,
                details={
                    "purchase_order_id": saved_po.purchase_order_id,
                    "order_intent_id": saved_intent.order_intent_id,
                    "quantity": qty,
                    "store_id": recommendation.store_id,
                    "sku": recommendation.sku,
                },
            )
            return _queued_payload(saved_intent, saved_po, outcome="queued")
        except Exception as exc:
            raced = order_intent_repository.get_by_idempotency_key(session, key)
            if raced is not None:
                po_raced = (
                    purchase_order_repository.get_purchase_order(
                        session, raced.purchase_order_id
                    )
                    if raced.purchase_order_id
                    else None
                )
                return _queued_payload(raced, po_raced, outcome="already_queued")
            raced_po = purchase_order_repository.get_purchase_order_by_approval(
                session, approval_id
            )
            if raced_po is not None:
                return {
                    "outcome": "already_queued",
                    "order_intent": None,
                    "purchase_order": raced_po.model_dump(mode="json"),
                    "status": raced_po.order_status,
                    "error": str(exc),
                }
            raise


def _intent_from_po(
    po: PurchaseOrder,
    *,
    key: str,
    released_by_type: str,
    released_by_label: str,
    product_name: str | None,
) -> OrderIntent:
    now = _now()
    unit_cost = _unit_cost(po.sku)
    qty = po.approved_final_quantity
    lines = _build_lines(
        store_id=po.store_id,
        sku=po.sku,
        product_name=product_name,
        quantity=qty,
        unit_cost=unit_cost,
    )
    return OrderIntent(
        order_intent_id=_intent_id(),
        recommendation_id=po.recommendation_id or "",
        approval_id=po.approval_id,
        purchase_order_id=po.purchase_order_id,
        status=po.order_status or ORDER_PENDING_ERP,  # type: ignore[arg-type]
        store_id=po.store_id,
        sku=po.sku,
        product_name=product_name,
        quantity=qty,
        unit_cost=unit_cost,
        amount=float(po.amount or lines[0].line_amount),
        vendor=po.vendor or _default_vendor_name(),
        lines=lines,
        source_run_id=po.source_run_id,
        approved_by=po.approved_by,
        released_by_type=released_by_type,  # type: ignore[arg-type]
        released_by_label=released_by_label,
        idempotency_key=key,
        mock_erp_reference=po.erp_reference,
        transmitted_at=po.transmitted_at,
        created_at=po.created_at or now,
        updated_at=now,
        user_id=po.user_id,
        session_id=po.session_id,
    )


def _queued_payload(
    intent: OrderIntent,
    po: PurchaseOrder | None,
    *,
    outcome: str,
) -> dict[str, Any]:
    try:
        from eventbus.events import EventType

        _publish_lifecycle_event(EventType.ERP_QUEUED, intent)
    except Exception:  # noqa: BLE001
        pass
    return {
        "outcome": outcome,
        "order_intent_id": intent.order_intent_id,
        "purchase_order_id": intent.purchase_order_id
        or (po.purchase_order_id if po else None),
        "approval_id": intent.approval_id,
        "recommendation_id": intent.recommendation_id,
        "status": intent.status,
        "order_intent": intent.model_dump(mode="json"),
        "purchase_order": po.model_dump(mode="json") if po else None,
    }



def _load_intent(
    session,
    *,
    order_intent_id: str | None = None,
    purchase_order_id: str | None = None,
) -> tuple[OrderIntent, PurchaseOrder | None]:
    intent: OrderIntent | None = None
    if order_intent_id:
        intent = order_intent_repository.get_order_intent(session, order_intent_id)
    elif purchase_order_id:
        po_lookup = purchase_order_repository.get_purchase_order(session, purchase_order_id)
        if po_lookup and po_lookup.recommendation_id:
            intent = order_intent_repository.get_by_recommendation(
                session, po_lookup.recommendation_id
            )
        if intent is None and po_lookup and po_lookup.approval_id:
            intent = order_intent_repository.get_by_approval(session, po_lookup.approval_id)
    if intent is None:
        raise ValueError("Order intent not found")
    po = None
    if intent.purchase_order_id:
        po = purchase_order_repository.get_purchase_order(session, intent.purchase_order_id)
    if po is None and purchase_order_id:
        po = purchase_order_repository.get_purchase_order(session, purchase_order_id)
    return intent, po


def _apply_lifecycle_to_po(po: PurchaseOrder | None, intent: OrderIntent) -> None:
    if po is None:
        return
    status = ols.normalize_status(intent.status)
    po.order_status = status
    po.status = status
    po.transmission_status = ols.transmission_status_for(status)
    po.erp_reference = intent.external_order_id or intent.mock_erp_reference
    if hasattr(po, "external_order_id"):
        po.external_order_id = intent.external_order_id or intent.mock_erp_reference
    if hasattr(po, "acknowledged_at"):
        po.acknowledged_at = intent.acknowledged_at
    po.transmitted_at = intent.transmitted_at
    if hasattr(po, "erp_provider"):
        po.erp_provider = intent.erp_provider
    if hasattr(po, "transmission_idempotency_key"):
        po.transmission_idempotency_key = intent.transmission_idempotency_key
    if hasattr(po, "last_error_code"):
        po.last_error_code = intent.last_error_code
    if hasattr(po, "last_attempt_at"):
        po.last_attempt_at = intent.last_attempt_at
    if hasattr(po, "next_retry_at"):
        po.next_retry_at = intent.next_retry_at
    if hasattr(po, "attempt_count"):
        po.attempt_count = intent.attempts
    po.transmission_error = intent.last_error_message or intent.last_error
    po.vendor = intent.vendor
    po.amount = intent.amount


def _publish_lifecycle_event(event_type: str, intent: OrderIntent, *, extra: dict | None = None) -> None:
    try:
        from eventbus.publisher import safe_publish

        safe_publish(
            event_type,
            aggregate_type="order_intent",
            aggregate_id=intent.order_intent_id,
            payload={
                "order_intent_id": intent.order_intent_id,
                "purchase_order_id": intent.purchase_order_id,
                "recommendation_id": intent.recommendation_id,
                "approval_id": intent.approval_id,
                "execution_id": intent.execution_id,
                "status": ols.normalize_status(intent.status),
                **dict(extra or {}),
            },
            actor="erp_lifecycle",
            correlation_id=intent.execution_id,
            metadata={
                "idempotency_key": f"{event_type}:{intent.order_intent_id}:{intent.status}"
            },
        )
    except Exception:  # noqa: BLE001
        pass


def _success_payload(intent: OrderIntent, *, outcome: str) -> dict[str, Any]:
    try:
        from eventbus.events import EventType

        if outcome in {"transmitted", "already_transmitted"}:
            _publish_lifecycle_event(EventType.ERP_SUBMITTED, intent)
            _publish_lifecycle_event(EventType.ERP_ACKNOWLEDGED, intent)
    except Exception:  # noqa: BLE001
        pass
    return {
        "outcome": outcome,
        "order_intent_id": intent.order_intent_id,
        "purchase_order_id": intent.purchase_order_id,
        "status": ols.normalize_status(intent.status),
        "status_label": ols.format_lifecycle_label(intent.status),
        "external_order_id": intent.external_order_id or intent.mock_erp_reference,
        "acknowledged_at": intent.acknowledged_at.isoformat() if intent.acknowledged_at else None,
        "erp_provider": intent.erp_provider,
        "attempts": intent.attempts,
        "erp": {
            "purchase_order_id": intent.purchase_order_id,
            "transmitted_at": intent.transmitted_at.isoformat() if intent.transmitted_at else None,
            "acknowledged_at": intent.acknowledged_at.isoformat() if intent.acknowledged_at else None,
            "vendor": intent.vendor,
            "lines": [line.model_dump(mode="json") for line in intent.lines],
            "amount": intent.amount,
            "status": ols.normalize_status(intent.status),
            "mock_erp_reference": intent.mock_erp_reference,
            "external_order_id": intent.external_order_id or intent.mock_erp_reference,
        },
        "transmission": {
            "success": True,
            "external_order_id": intent.external_order_id or intent.mock_erp_reference,
            "provider": intent.erp_provider,
        },
    }


def transmit_order_intent(
    *,
    order_intent_id: str | None = None,
    purchase_order_id: str | None = None,
    actor: str = "system",
    actor_role: str | None = None,
    execution_id: str | None = None,
    mock_scenario: str | None = None,
) -> dict[str, Any]:
    """Controlled ERP transmission entry point. Idempotent per OrderIntent."""
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_create_purchase_order(actor_role),
            "transmit an order to ERP",
        )
    if not order_intent_id and not purchase_order_id:
        raise ValueError("order_intent_id or purchase_order_id is required")

    init_db()
    with get_session() as session:
        intent, po = _load_intent(
            session, order_intent_id=order_intent_id, purchase_order_id=purchase_order_id
        )
        status = ols.normalize_status(intent.status)

        if ols.is_terminal_success(status) or (
            (intent.external_order_id or intent.mock_erp_reference)
            and status not in {ols.TRANSMITTING, ols.TRANSMISSION_FAILED, ols.RETRY_PENDING}
        ):
            return {
                **_success_payload(intent, outcome="already_transmitted"),
                "outcome": "already_transmitted",
            }

        if status == ols.CANCELLED:
            raise ValueError("Cannot transmit a cancelled order")
        if status == ols.ERP_REJECTED:
            raise ValueError("Cannot transmit an ERP-rejected order")

        # Crash recovery: transmitting with prior external id → complete idempotently
        if status == ols.TRANSMITTING and (intent.external_order_id or intent.mock_erp_reference):
            intent = intent.model_copy(
                update={"status": ols.COMPLETED, "updated_at": _now()}
            )
            order_intent_repository.save_order_intent(session, intent)
            _apply_lifecycle_to_po(po, intent)
            if po is not None:
                purchase_order_repository.update_purchase_order(session, po)
            return _success_payload(intent, outcome="already_transmitted")

        if status not in {
            ols.QUEUED_FOR_ERP,
            ols.RETRY_PENDING,
            ols.TRANSMISSION_FAILED,
            ols.TRANSMITTING,
        }:
            raise ols.InvalidLifecycleTransition(status, ols.TRANSMITTING)

        tx_key = intent.transmission_idempotency_key or ols.transmission_idempotency_key(
            intent.order_intent_id
        )
        now = _now()
        if status != ols.TRANSMITTING:
            ols.assert_transition(status, ols.TRANSMITTING)

        intent = intent.model_copy(
            update={
                "status": ols.TRANSMITTING,
                "transmission_idempotency_key": tx_key,
                "updated_at": now,
                "attempts": int(intent.attempts or 0) + 1,
                "last_attempt_at": now,
                "last_error": None,
                "last_error_code": None,
                "last_error_message": None,
                "execution_id": execution_id or intent.execution_id,
            }
        )
        order_intent_repository.save_order_intent(session, intent)
        _apply_lifecycle_to_po(po, intent)
        if po is not None:
            purchase_order_repository.update_purchase_order(session, po)

        payload = dict(intent.payload or {})
        payload.update(
            {
                "purchase_order_id": intent.purchase_order_id,
                "vendor": intent.vendor,
                "lines": [line.model_dump(mode="json") for line in intent.lines],
                "amount": intent.amount,
                "unit_cost": intent.unit_cost,
                "sku": intent.sku,
                "store_id": intent.store_id,
                "approved_final_quantity": intent.quantity,
                "quantity": intent.quantity,
                "transmission_idempotency_key": tx_key,
                "order_intent_id": intent.order_intent_id,
            }
        )
        if mock_scenario:
            payload["mock_scenario"] = mock_scenario

        audit_repository.write_audit_event(
            session,
            "erp_transmission_started",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=intent.recommendation_id,
            approval_id=intent.approval_id,
            purchase_order_id=intent.purchase_order_id,
            store_id=intent.store_id,
            sku=intent.sku,
            details={
                "order_intent_id": intent.order_intent_id,
                "execution_id": intent.execution_id,
                "attempt": intent.attempts,
                "provider": "mock",
                "transmission_idempotency_key": tx_key,
                "store_id": intent.store_id,
                "sku": intent.sku,
            },
        )
        intent_id = intent.order_intent_id

    result: ERPTransmissionResult = erp_service.transmit_purchase_order_payload(payload)
    now = _now()

    with get_session() as session:
        intent, po = _load_intent(session, order_intent_id=intent_id)

        if ols.is_terminal_success(intent.status) and (
            intent.external_order_id or intent.mock_erp_reference
        ):
            return _success_payload(intent, outcome="already_transmitted")

        if result.success or result.status == ERP_OUTCOME_ACCEPTED:
            external_id = (
                result.external_order_id or result.provider_reference or result.erp_reference
            )
            ack_at = result.acknowledged_at or now
            submitted = result.submitted_at or now
            provider = result.provider_name or "Mock ERP"
            ols.assert_transition(ols.TRANSMITTING, ols.ERP_ACKNOWLEDGED)
            ols.assert_transition(ols.ERP_ACKNOWLEDGED, ols.COMPLETED)
            intent = intent.model_copy(
                update={
                    "status": ols.COMPLETED,
                    "mock_erp_reference": external_id,
                    "external_order_id": external_id,
                    "erp_provider": provider,
                    "transmitted_at": submitted,
                    "acknowledged_at": ack_at,
                    "last_error": None,
                    "last_error_code": None,
                    "last_error_message": None,
                    "next_retry_at": None,
                    "updated_at": now,
                    "vendor": (result.raw or {}).get("vendor") or intent.vendor,
                    "amount": float(
                        (result.raw or {}).get("amount", intent.amount) or intent.amount
                    ),
                }
            )
            order_intent_repository.save_order_intent(session, intent)
            _apply_lifecycle_to_po(po, intent)
            if po is not None and (result.raw or {}).get("lines"):
                po.lines = list((result.raw or {})["lines"])
            if po is not None:
                purchase_order_repository.update_purchase_order(session, po)

            audit_repository.write_audit_event(
                session,
                "erp_order_acknowledged",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=intent.recommendation_id,
                approval_id=intent.approval_id,
                purchase_order_id=intent.purchase_order_id,
                details={
                    "order_intent_id": intent.order_intent_id,
                    "execution_id": intent.execution_id,
                    "external_order_id": external_id,
                    "provider": provider,
                    "attempt": intent.attempts,
                    "acknowledgement_code": result.acknowledgement_code,
                },
            )
            audit_repository.write_audit_event(
                session,
                "erp_transmission_succeeded",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=intent.recommendation_id,
                approval_id=intent.approval_id,
                purchase_order_id=intent.purchase_order_id,
                details={
                    "order_intent_id": intent.order_intent_id,
                    "execution_id": intent.execution_id,
                    "external_order_id": external_id,
                    "provider": provider,
                    "attempt": intent.attempts,
                    "status": ols.COMPLETED,
                },
            )
            audit_repository.write_audit_event(
                session,
                "order_transmitted",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=intent.recommendation_id,
                approval_id=intent.approval_id,
                purchase_order_id=intent.purchase_order_id,
                details={
                    "order_intent_id": intent.order_intent_id,
                    "mock_erp_reference": external_id,
                    "adapter": result.adapter,
                },
            )
            return {
                **_success_payload(intent, outcome="transmitted"),
                "outcome": "transmitted",
                "status": ols.COMPLETED,
            }

        error = (
            result.error_message or result.message or result.error or "ERP transmission failed"
        )
        error_code = result.error_code or "erp_temporary_failure"
        is_rejection = (not result.retryable) and (
            result.status == ERP_OUTCOME_REJECTED or error_code == "erp_business_rejected"
        )

        if is_rejection:
            ols.assert_transition(ols.TRANSMITTING, ols.ERP_REJECTED)
            intent = intent.model_copy(
                update={
                    "status": ols.ERP_REJECTED,
                    "last_error": error,
                    "last_error_code": error_code,
                    "last_error_message": error,
                    "erp_provider": result.provider_name,
                    "next_retry_at": None,
                    "updated_at": now,
                }
            )
            order_intent_repository.save_order_intent(session, intent)
            _apply_lifecycle_to_po(po, intent)
            if po is not None:
                purchase_order_repository.update_purchase_order(session, po)
            audit_repository.write_audit_event(
                session,
                "erp_order_rejected",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=intent.recommendation_id,
                approval_id=intent.approval_id,
                purchase_order_id=intent.purchase_order_id,
                details={
                    "order_intent_id": intent.order_intent_id,
                    "execution_id": intent.execution_id,
                    "provider": result.provider_name,
                    "attempt": intent.attempts,
                    "error_code": error_code,
                    "error": error,
                },
            )
            try:
                from eventbus.events import EventType

                _publish_lifecycle_event(
                    EventType.ERP_REJECTED,
                    intent,
                    extra={"error_code": error_code, "error": error},
                )
            except Exception:  # noqa: BLE001
                pass
            return {
                "outcome": "erp_rejected",
                "order_intent_id": intent.order_intent_id,
                "purchase_order_id": intent.purchase_order_id,
                "status": ols.ERP_REJECTED,
                "status_label": ols.format_lifecycle_label(ols.ERP_REJECTED),
                "error": error,
                "error_code": error_code,
                "retryable": False,
                "erp": None,
            }

        ols.assert_transition(ols.TRANSMITTING, ols.TRANSMISSION_FAILED)
        max_attempts = max(1, int(ERP_MAX_RETRY_ATTEMPTS or 3))
        next_status = ols.TRANSMISSION_FAILED
        next_retry = None
        if intent.attempts < max_attempts and result.retryable:
            ols.assert_transition(ols.TRANSMISSION_FAILED, ols.RETRY_PENDING)
            next_status = ols.RETRY_PENDING
            next_retry = now + timedelta(seconds=max(1, int(ERP_RETRY_DELAY_SECONDS or 60)))

        intent = intent.model_copy(
            update={
                "status": next_status,
                "last_error": error,
                "last_error_code": error_code,
                "last_error_message": error,
                "erp_provider": result.provider_name,
                "next_retry_at": next_retry,
                "updated_at": now,
            }
        )
        order_intent_repository.save_order_intent(session, intent)
        _apply_lifecycle_to_po(po, intent)
        if po is not None:
            purchase_order_repository.update_purchase_order(session, po)

        audit_repository.write_audit_event(
            session,
            "erp_transmission_failed",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=intent.recommendation_id,
            approval_id=intent.approval_id,
            purchase_order_id=intent.purchase_order_id,
            details={
                "order_intent_id": intent.order_intent_id,
                "execution_id": intent.execution_id,
                "provider": result.provider_name,
                "attempt": intent.attempts,
                "error_code": error_code,
                "error": error,
                "retryable": bool(result.retryable),
            },
        )
        if next_status == ols.RETRY_PENDING:
            audit_repository.write_audit_event(
                session,
                "erp_retry_scheduled",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=intent.recommendation_id,
                approval_id=intent.approval_id,
                purchase_order_id=intent.purchase_order_id,
                details={
                    "order_intent_id": intent.order_intent_id,
                    "attempt": intent.attempts,
                    "next_retry_at": next_retry.isoformat() if next_retry else None,
                    "max_attempts": max_attempts,
                },
            )
        audit_repository.write_audit_event(
            session,
            "order_transmission_failed",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=intent.recommendation_id,
            approval_id=intent.approval_id,
            purchase_order_id=intent.purchase_order_id,
            details={
                "order_intent_id": intent.order_intent_id,
                "error": error,
                "adapter": result.adapter,
            },
        )
        return {
            "outcome": "failed" if next_status == ols.TRANSMISSION_FAILED else "retry_pending",
            "order_intent_id": intent.order_intent_id,
            "purchase_order_id": intent.purchase_order_id,
            "status": next_status,
            "status_label": ols.format_lifecycle_label(next_status),
            "error": error,
            "error_code": error_code,
            "retryable": bool(result.retryable) and next_status == ols.RETRY_PENDING,
            "attempts": intent.attempts,
            "next_retry_at": next_retry.isoformat() if next_retry else None,
            "erp": None,
        }


def transmit_order_to_erp(
    *,
    order_intent_id: str | None = None,
    purchase_order_id: str | None = None,
    actor: str = "system",
    actor_role: str | None = None,
    execution_id: str | None = None,
    mock_scenario: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for transmit_order_intent."""
    return transmit_order_intent(
        order_intent_id=order_intent_id,
        purchase_order_id=purchase_order_id,
        actor=actor,
        actor_role=actor_role,
        execution_id=execution_id,
        mock_scenario=mock_scenario,
    )


def retry_failed_order(
    *,
    order_intent_id: str | None = None,
    purchase_order_id: str | None = None,
    actor: str = "system",
    actor_role: str | None = None,
) -> dict[str, Any]:
    """Manual retry for retryable technical failures only."""
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_retry_blocked(actor_role),
            "retry ERP transmission",
        )
    init_db()
    with get_session() as session:
        intent, po = _load_intent(
            session, order_intent_id=order_intent_id, purchase_order_id=purchase_order_id
        )
        status = ols.normalize_status(intent.status)
        if ols.is_terminal_success(status):
            return transmit_order_intent(
                order_intent_id=intent.order_intent_id,
                actor=actor,
                actor_role=actor_role,
            )
        if status == ols.ERP_REJECTED:
            raise ValueError("ERP business rejection cannot be retried")
        if status == ols.CANCELLED:
            raise ValueError("Cancelled orders cannot be retried")
        if not ols.can_manual_retry(status) and status != ols.QUEUED_FOR_ERP:
            raise ValueError(f"Cannot retry order in status {status}")

        max_attempts = max(1, int(ERP_MAX_RETRY_ATTEMPTS or 3))
        if intent.attempts >= max_attempts and status != ols.QUEUED_FOR_ERP:
            raise ValueError(
                f"Retry attempts exhausted ({intent.attempts}/{max_attempts})"
            )

        now = _now()
        if status == ols.TRANSMISSION_FAILED:
            ols.assert_transition(status, ols.RETRY_PENDING)
            intent = intent.model_copy(
                update={"status": ols.RETRY_PENDING, "updated_at": now}
            )
            order_intent_repository.save_order_intent(session, intent)
            _apply_lifecycle_to_po(po, intent)
            if po is not None:
                purchase_order_repository.update_purchase_order(session, po)
            audit_repository.write_audit_event(
                session,
                "erp_retry_started",
                actor=actor,
                actor_role=actor_role,
                recommendation_id=intent.recommendation_id,
                approval_id=intent.approval_id,
                purchase_order_id=intent.purchase_order_id,
                details={
                    "order_intent_id": intent.order_intent_id,
                    "attempt": intent.attempts,
                    "from_status": status,
                },
            )
        intent_id = intent.order_intent_id

    return transmit_order_intent(
        order_intent_id=intent_id,
        actor=actor,
        actor_role=actor_role,
    )


def cancel_order_intent(
    *,
    order_intent_id: str | None = None,
    purchase_order_id: str | None = None,
    actor: str = "system",
    actor_role: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancel only while queued_for_erp. Acknowledged orders cannot be cancelled locally."""
    if actor_role is not None:
        auth_service.require_permission(
            actor_role,
            auth_service.can_create_purchase_order(actor_role),
            "cancel a queued order",
        )
    init_db()
    with get_session() as session:
        intent, po = _load_intent(
            session, order_intent_id=order_intent_id, purchase_order_id=purchase_order_id
        )
        status = ols.normalize_status(intent.status)
        if ols.is_acknowledged_or_later(status):
            raise ValueError(
                "ERP cancellation is not available for acknowledged orders."
            )
        if status == ols.CANCELLED:
            return {
                "outcome": "already_cancelled",
                "order_intent_id": intent.order_intent_id,
                "status": ols.CANCELLED,
            }
        if not ols.can_cancel(status):
            raise ValueError(
                f"Cannot cancel order in status {status}. "
                "Only queued orders may be cancelled before ERP acknowledgement."
            )
        ols.assert_transition(status, ols.CANCELLED)
        now = _now()
        intent = intent.model_copy(
            update={
                "status": ols.CANCELLED,
                "updated_at": now,
                "last_error_message": reason,
            }
        )
        order_intent_repository.save_order_intent(session, intent)
        _apply_lifecycle_to_po(po, intent)
        if po is not None:
            purchase_order_repository.update_purchase_order(session, po)
        audit_repository.write_audit_event(
            session,
            "order_cancelled",
            actor=actor,
            actor_role=actor_role,
            recommendation_id=intent.recommendation_id,
            approval_id=intent.approval_id,
            purchase_order_id=intent.purchase_order_id,
            details={
                "order_intent_id": intent.order_intent_id,
                "execution_id": intent.execution_id,
                "reason": reason,
                "attempt": intent.attempts,
            },
        )
        return {
            "outcome": "cancelled",
            "order_intent_id": intent.order_intent_id,
            "purchase_order_id": intent.purchase_order_id,
            "status": ols.CANCELLED,
            "status_label": ols.format_lifecycle_label(ols.CANCELLED),
        }


def get_order_intent(order_intent_id: str) -> dict[str, Any] | None:
    init_db()
    with get_session() as session:
        intent = order_intent_repository.get_order_intent(session, order_intent_id)
    if intent is None:
        return None
    payload = intent.model_dump(mode="json")
    payload["status"] = ols.normalize_status(intent.status)
    payload["status_label"] = ols.format_lifecycle_label(intent.status)
    payload.update(ols.status_summary(intent.status))
    return payload


def get_order_lifecycle_metrics() -> dict[str, Any]:
    """Operational counters for System Health (order-level, not provider health)."""
    init_db()
    with get_session() as session:
        intents = order_intent_repository.list_order_intents(session, limit=500)
    counts = {
        "queued_for_erp": 0,
        "transmission_failed": 0,
        "retry_pending": 0,
        "erp_rejected": 0,
        "transmitting": 0,
        "completed": 0,
    }
    oldest_queued = None
    for intent in intents:
        st = ols.normalize_status(intent.status)
        if st in counts:
            counts[st] += 1
        if st == ols.QUEUED_FOR_ERP:
            if oldest_queued is None or intent.created_at < oldest_queued:
                oldest_queued = intent.created_at
    return {
        **counts,
        "oldest_queued_order_at": oldest_queued.isoformat() if oldest_queued else None,
    }

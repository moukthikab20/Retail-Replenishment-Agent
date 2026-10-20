"""Database-backed memory reader — uses repositories / ORM, not business services."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.connection import get_session, init_db
from database.models import ApprovalRow
from memory.contracts import MemoryQuery, MemoryRecord
from memory.types import MemoryType
from repositories import (
    audit_repository,
    order_intent_repository,
    purchase_order_repository,
    recommendation_repository,
)


def _parse_details(raw: str | None) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


class DatabaseMemoryReader:
    """Fetches typed historical memory from existing persisted tables."""

    def fetch(self, query: MemoryQuery) -> list[MemoryRecord]:
        init_db()
        types = query.memory_types or list(MemoryType)
        limit = max(1, min(int(query.limit or 10), 50))
        records: list[MemoryRecord] = []
        with get_session() as session:
            for mem_type in types:
                remaining = limit - len(records)
                if remaining <= 0:
                    break
                records.extend(self._fetch_type(session, mem_type, query, remaining))
        return records[:limit]

    def _fetch_type(
        self,
        session,
        mem_type: MemoryType,
        query: MemoryQuery,
        limit: int,
    ) -> list[MemoryRecord]:
        dispatch = {
            MemoryType.RECOMMENDATION: self._recommendations,
            MemoryType.APPROVAL: self._approvals,
            MemoryType.DECISION: self._decisions,
            MemoryType.EXECUTION: self._executions,
            MemoryType.ERP: self._erp,
            MemoryType.CONVERSATION: self._conversations,
            MemoryType.POLICY: self._policy,
            MemoryType.SUPPLIER: self._supplier,
            MemoryType.INVENTORY: self._inventory,
        }
        handler = dispatch.get(mem_type)
        if handler is None:
            return []
        return handler(session, query, limit)

    def _recommendations(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        if query.store_id and query.sku:
            rows = recommendation_repository.list_recommendations_for_store_sku(
                session, query.store_id, query.sku, limit=limit
            )
        elif query.recommendation_id:
            one = recommendation_repository.get_recommendation(
                session, query.recommendation_id
            )
            rows = [one] if one else []
        else:
            rows = recommendation_repository.list_recent_recommendations(
                session, limit=limit
            )
        out: list[MemoryRecord] = []
        for row in rows:
            if row is None:
                continue
            rec_id = getattr(row, "recommendation_id", None)
            store_id = getattr(row, "store_id", None)
            sku = getattr(row, "sku", None)
            if query.store_id and store_id and store_id != query.store_id:
                continue
            if query.sku and sku and sku != query.sku:
                continue
            qty = getattr(row, "agent_recommended_quantity", None)
            risk = getattr(row, "risk_level", None)
            status = getattr(row, "status", None)
            created = getattr(row, "created_at", None)
            out.append(
                MemoryRecord(
                    record_id=str(rec_id),
                    memory_type=MemoryType.RECOMMENDATION,
                    title=f"Recommendation {rec_id}",
                    summary=f"status={status} risk={risk} qty={qty}",
                    occurred_at=created if isinstance(created, datetime) else None,
                    store_id=store_id,
                    sku=sku,
                    recommendation_id=rec_id,
                    source="database",
                    payload={"status": status, "risk_level": risk, "quantity": qty},
                )
            )
            if len(out) >= limit:
                break
        return out

    def _approvals(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        out: list[MemoryRecord] = []
        if query.approval_id:
            row = session.get(ApprovalRow, query.approval_id)
            rows = [row] if row else []
        elif query.recommendation_id:
            stmt = (
                select(ApprovalRow)
                .where(ApprovalRow.recommendation_id == query.recommendation_id)
                .order_by(ApprovalRow.requested_at.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt))
        else:
            stmt = (
                select(ApprovalRow)
                .order_by(ApprovalRow.requested_at.desc())
                .limit(limit)
            )
            rows = list(session.scalars(stmt))
        for row in rows:
            if row is None:
                continue
            out.append(
                MemoryRecord(
                    record_id=str(row.approval_id),
                    memory_type=MemoryType.APPROVAL,
                    title=f"Approval {row.approval_id}",
                    summary=f"status={row.status} required_role={row.required_role}",
                    occurred_at=row.approved_at or row.requested_at,
                    recommendation_id=row.recommendation_id,
                    approval_id=row.approval_id,
                    source="database",
                    payload={
                        "status": row.status,
                        "required_role": row.required_role,
                        "approved_final_quantity": row.approved_final_quantity,
                    },
                )
            )
            if len(out) >= limit:
                break
        return out

    def _decisions(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        events = audit_repository.list_audit_events(
            session,
            recommendation_id=query.recommendation_id,
            store_id=query.store_id,
            sku=query.sku,
            limit=limit * 5,
        )
        decision_types = {
            "human_review_submitted",
            "recommendation_approved",
            "recommendation_declined",
            "recommendation_auto_released",
            "recommendation_blocked",
            "quantity_adjusted",
            "formal_approval_granted",
            "formal_approval_rejected",
        }
        out: list[MemoryRecord] = []
        for event in events:
            if event.event_type not in decision_types:
                continue
            details = _parse_details(event.details_json)
            out.append(
                MemoryRecord(
                    record_id=event.event_id,
                    memory_type=MemoryType.DECISION,
                    title=event.event_type,
                    summary=str(
                        details.get("decision_action") or details.get("status") or ""
                    ),
                    occurred_at=event.timestamp,
                    store_id=event.store_id,
                    sku=event.sku,
                    recommendation_id=event.recommendation_id,
                    approval_id=event.approval_id,
                    source="database",
                    payload=details,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _executions(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        rows = audit_repository.list_agent_run_states(
            session,
            recommendation_id=query.recommendation_id,
            limit=limit,
        )
        out: list[MemoryRecord] = []
        for row in rows:
            status = row.status
            err = row.last_error_code
            is_failure = status in {"failed", "retry_pending"} or bool(err)
            if query.include_failures is False and status == "failed":
                continue
            out.append(
                MemoryRecord(
                    record_id=str(row.run_id),
                    memory_type=MemoryType.EXECUTION,
                    title=f"Execution {row.run_id}",
                    summary=f"type={row.execution_type} status={status}",
                    occurred_at=row.created_at,
                    recommendation_id=row.recommendation_id,
                    approval_id=row.approval_id,
                    execution_id=row.run_id,
                    source="database",
                    payload={
                        "status": status,
                        "execution_type": row.execution_type,
                        "is_failure": is_failure,
                        "last_error_code": err,
                    },
                )
            )
            if len(out) >= limit:
                break
        return out

    def _erp(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        intents = order_intent_repository.list_order_intents(session, limit=limit * 3)
        out: list[MemoryRecord] = []
        for intent in intents:
            if query.store_id and intent.store_id != query.store_id:
                continue
            if query.sku and intent.sku != query.sku:
                continue
            if query.recommendation_id and intent.recommendation_id not in {
                None,
                query.recommendation_id,
            }:
                continue
            if query.purchase_order_id and intent.purchase_order_id not in {
                None,
                query.purchase_order_id,
            }:
                continue
            is_failure = intent.status in {
                "transmission_failed",
                "retry_pending",
                "erp_rejected",
                "failed",
            }
            if query.include_failures is False and is_failure:
                continue
            out.append(
                MemoryRecord(
                    record_id=intent.order_intent_id,
                    memory_type=MemoryType.ERP,
                    title=f"OrderIntent {intent.order_intent_id}",
                    summary=(
                        f"status={intent.status} external="
                        f"{intent.external_order_id or intent.mock_erp_reference}"
                    ),
                    occurred_at=intent.updated_at or intent.created_at,
                    store_id=intent.store_id,
                    sku=intent.sku,
                    recommendation_id=intent.recommendation_id,
                    approval_id=intent.approval_id,
                    purchase_order_id=intent.purchase_order_id,
                    source="database",
                    payload={
                        "status": intent.status,
                        "external_order_id": intent.external_order_id
                        or intent.mock_erp_reference,
                        "is_failure": is_failure,
                        "attempts": intent.attempts,
                    },
                )
            )
            if len(out) >= limit:
                break
        return out

    def _conversations(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        events = audit_repository.list_audit_events(
            session,
            recommendation_id=query.recommendation_id,
            store_id=query.store_id,
            sku=query.sku,
            limit=limit * 5,
        )
        out: list[MemoryRecord] = []
        for event in events:
            et = (event.event_type or "").lower()
            if "follow_up" not in et and et not in {
                "agent_follow_up_question",
                "agent_follow_up_answered",
            }:
                continue
            details = _parse_details(event.details_json)
            out.append(
                MemoryRecord(
                    record_id=event.event_id,
                    memory_type=MemoryType.CONVERSATION,
                    title="Follow-up conversation",
                    summary=str(
                        details.get("question_type") or details.get("answer") or ""
                    )[:200],
                    occurred_at=event.timestamp,
                    recommendation_id=event.recommendation_id,
                    store_id=event.store_id,
                    sku=event.sku,
                    source="database",
                    payload=details,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _policy(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        events = audit_repository.list_audit_events(
            session,
            recommendation_id=query.recommendation_id,
            store_id=query.store_id,
            sku=query.sku,
            limit=limit * 5,
        )
        out: list[MemoryRecord] = []
        for event in events:
            et = (event.event_type or "").lower()
            if et not in {"policy_evaluated", "recommendation_auto_released", "recommendation_blocked"}:
                if "policy" not in et:
                    continue
            details = _parse_details(event.details_json)
            out.append(
                MemoryRecord(
                    record_id=event.event_id,
                    memory_type=MemoryType.POLICY,
                    title="Policy evaluation",
                    summary=str(
                        details.get("disposition") or details.get("status") or event.event_type
                    ),
                    occurred_at=event.timestamp,
                    recommendation_id=event.recommendation_id,
                    store_id=event.store_id,
                    sku=event.sku,
                    source="database",
                    payload=details,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _supplier(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        orders = purchase_order_repository.list_purchase_orders(session, limit=limit * 3)
        out: list[MemoryRecord] = []
        seen: set[str] = set()
        for po in orders:
            vendor = po.vendor or "Demo Vendor"
            if query.supplier_id and str(vendor) != str(query.supplier_id):
                continue
            if query.store_id and po.store_id != query.store_id:
                continue
            if query.sku and po.sku != query.sku:
                continue
            key = f"{vendor}:{po.store_id}:{po.sku}"
            if key in seen:
                continue
            seen.add(key)
            out.append(
                MemoryRecord(
                    record_id=f"SUP-{len(seen)}-{po.purchase_order_id}",
                    memory_type=MemoryType.SUPPLIER,
                    title=str(vendor),
                    summary=f"Recent order vendor for {po.store_id}/{po.sku}",
                    occurred_at=po.created_at,
                    store_id=po.store_id,
                    sku=po.sku,
                    supplier_id=str(vendor),
                    purchase_order_id=po.purchase_order_id,
                    source="database",
                    payload={"vendor": vendor},
                )
            )
            if len(out) >= limit:
                break
        return out

    def _inventory(self, session, query: MemoryQuery, limit: int) -> list[MemoryRecord]:
        events = audit_repository.list_audit_events(
            session,
            recommendation_id=query.recommendation_id,
            store_id=query.store_id,
            sku=query.sku,
            limit=limit * 5,
        )
        out: list[MemoryRecord] = []
        for event in events:
            et = (event.event_type or "").lower()
            if et not in {
                "recommendation_generated",
                "recommendation_created",
            }:
                continue
            details = _parse_details(event.details_json)
            out.append(
                MemoryRecord(
                    record_id=event.event_id,
                    memory_type=MemoryType.INVENTORY,
                    title=f"Inventory context {event.store_id}/{event.sku}",
                    summary=str(details.get("risk_level") or ""),
                    occurred_at=event.timestamp,
                    store_id=event.store_id,
                    sku=event.sku,
                    recommendation_id=event.recommendation_id,
                    source="database",
                    payload=details,
                )
            )
            if len(out) >= limit:
                break
        return out

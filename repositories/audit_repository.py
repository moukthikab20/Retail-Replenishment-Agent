"""Audit event and agent run-state persistence.

Events are append-only — rows are never updated or deleted by this module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AgentRunStateRow, AuditEventRow

# Legacy / operational event names → Checkpoint 11 business events (append-only dual-write).
_BUSINESS_ALIASES: dict[str, str] = {
    "replenishment_run_started": "batch_started",
    "replenishment_run_completed": "batch_completed",
    "replenishment_run_failed": "batch_completed",
    "recommendation_generated": "recommendation_created",
    "approval_requested": "formal_approval_requested",
    "approval_granted": "formal_approval_granted",
    "approval_rejected": "formal_approval_rejected",
    "order_intent_queued": "order_queued",
    "order_transmitted": "erp_transmission_succeeded",
    "order_transmission_failed": "erp_transmission_failed",
    "erp_transmission_sent": "erp_transmission_succeeded",
    "recommendation_adjusted": "quantity_adjusted",
    # Batch item failure: keep legacy row + emit checkpoint name.
    "replenishment_run_item_failed": "replenishment_item_failed",
}


def write_audit_event(
    session: Session,
    event_type: str,
    *,
    actor: str = "system",
    actor_type: str | None = None,
    actor_id: str | None = None,
    actor_role: str | None = None,
    run_id: str | None = None,
    recommendation_id: str | None = None,
    review_id: str | None = None,
    approval_id: str | None = None,
    purchase_order_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    authentication_source: str | None = None,
    timestamp: datetime | None = None,
    _emit_business_alias: bool = True,
) -> str:
    """Insert a new audit event. Never overwrites an existing event_id."""
    payload = dict(details or {})
    if authentication_source and "authentication_source" not in payload:
        payload["authentication_source"] = authentication_source
    sanitized = _sanitize(payload)
    store_value = store_id or _detail_str(sanitized, "store_id")
    sku_value = sku or _detail_str(sanitized, "sku")
    actor_id_value = actor_id or actor
    actor_type_value = actor_type or _infer_actor_type(actor)
    event_id = f"EVT-{uuid4().hex[:12]}"
    row = AuditEventRow(
        event_id=event_id,
        run_id=run_id,
        recommendation_id=recommendation_id,
        review_id=review_id,
        approval_id=approval_id,
        purchase_order_id=purchase_order_id,
        actor=actor,
        actor_type=actor_type_value,
        actor_id=actor_id_value,
        actor_role=actor_role,
        timestamp=timestamp or datetime.now(timezone.utc),
        event_type=event_type,
        details_json=json.dumps(sanitized, default=str),
        store_id=store_value,
        sku=sku_value,
        correlation_id=correlation_id,
        user_id=user_id,
        session_id=session_id,
    )
    session.add(row)
    session.flush()

    # Dual-write canonical business event without replacing the legacy row.
    alias = _BUSINESS_ALIASES.get(event_type) if _emit_business_alias else None
    if alias and alias != event_type:
        write_audit_event(
            session,
            alias,
            actor=actor,
            actor_type=actor_type_value,
            actor_id=actor_id_value,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            review_id=review_id,
            approval_id=approval_id,
            purchase_order_id=purchase_order_id,
            store_id=store_value,
            sku=sku_value,
            correlation_id=correlation_id,
            details=sanitized,
            user_id=user_id,
            session_id=session_id,
            authentication_source=authentication_source,
            timestamp=row.timestamp,
            _emit_business_alias=False,
        )
    return event_id


def _detail_str(details: dict[str, Any], key: str) -> str | None:
    value = details.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _infer_actor_type(actor: str | None) -> str:
    value = (actor or "system").strip().lower()
    if value in {"system", "policy_engine", "erp_adapter", "mock_erp"}:
        return "system"
    if (
        value in {"scheduler", "cron", "job", "replenishment_scheduler", "render-cron"}
        or value.endswith("-cron")
        or "scheduler" in value
    ):
        return "scheduler"
    if value in {"agent", "assistant"} or value.startswith("agent"):
        return "agent"
    if value.startswith("usr-") or value.startswith("user-") or "@" in value:
        return "human"
    if value == "system":
        return "system"
    return "human"


def save_agent_run_state(
    session: Session,
    *,
    run_id: str,
    state_json: str,
    status: str = "paused",
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    pending_tool_name: str | None = None,
    pending_tool_args: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    idempotency_key: str | None = None,
    execution_type: str | None = None,
    current_step: str | None = None,
    next_action: str | None = None,
    attempt_count: int | None = None,
    max_attempts: int | None = None,
    waiting_reason: str | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    correlation_id: str | None = None,
    version: int | None = None,
    completed_at: datetime | None = None,
    expected_version: int | None = None,
) -> AgentRunStateRow:
    """
    Upsert durable agent execution state.

    When expected_version is provided on an existing row, rejects mismatches
    (optimistic concurrency) instead of last-write-wins.
    """
    from services.errors import AppError

    now = datetime.now(timezone.utc)
    row = session.get(AgentRunStateRow, run_id)
    args_json = json.dumps(pending_tool_args or {}, default=str)
    if row is None and idempotency_key:
        existing_key = session.scalars(
            select(AgentRunStateRow).where(AgentRunStateRow.idempotency_key == idempotency_key)
        ).first()
        if existing_key is not None:
            row = existing_key
    if row is None:
        row = AgentRunStateRow(
            run_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            status=status,
            state_json=state_json,
            pending_tool_name=pending_tool_name,
            pending_tool_args_json=args_json,
            created_at=now,
            updated_at=now,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            execution_type=execution_type,
            current_step=current_step,
            next_action=next_action,
            attempt_count=int(attempt_count if attempt_count is not None else 0),
            max_attempts=int(max_attempts if max_attempts is not None else 3),
            waiting_reason=waiting_reason,
            last_error_code=last_error_code,
            last_error_message=last_error_message,
            correlation_id=correlation_id,
            version=int(version if version is not None else 1),
            completed_at=completed_at,
        )
        session.add(row)
    else:
        current_version = int(getattr(row, "version", 1) or 1)
        if expected_version is not None and current_version != int(expected_version):
            raise AppError(
                f"Stale execution version: expected {expected_version}, "
                f"current {current_version}",
                code="concurrency_conflict",
            )
        row.recommendation_id = recommendation_id or row.recommendation_id
        row.approval_id = approval_id or row.approval_id
        row.status = status
        row.state_json = state_json
        row.pending_tool_name = pending_tool_name
        row.pending_tool_args_json = args_json
        row.updated_at = now
        if user_id is not None:
            row.user_id = user_id
        if session_id is not None:
            row.session_id = session_id
        if idempotency_key is not None:
            row.idempotency_key = idempotency_key
        if execution_type is not None:
            row.execution_type = execution_type
        if current_step is not None:
            row.current_step = current_step
        if next_action is not None:
            row.next_action = next_action
        if attempt_count is not None:
            row.attempt_count = int(attempt_count)
        if max_attempts is not None:
            row.max_attempts = int(max_attempts)
        if waiting_reason is not None:
            row.waiting_reason = waiting_reason
        if last_error_code is not None:
            row.last_error_code = last_error_code
        if last_error_message is not None:
            row.last_error_message = last_error_message
        if correlation_id is not None:
            row.correlation_id = correlation_id
        if completed_at is not None:
            row.completed_at = completed_at
        if version is not None:
            row.version = int(version)
        elif expected_version is not None:
            row.version = current_version + 1
    session.flush()
    return row


def get_agent_run_state(session: Session, run_id: str) -> AgentRunStateRow | None:
    return session.get(AgentRunStateRow, run_id)


def get_agent_run_by_idempotency_key(
    session: Session, idempotency_key: str
) -> AgentRunStateRow | None:
    return session.scalars(
        select(AgentRunStateRow).where(AgentRunStateRow.idempotency_key == idempotency_key)
    ).first()


def get_paused_run_by_approval(
    session: Session,
    approval_id: str,
) -> AgentRunStateRow | None:
    """Latest paused / waiting_for_human HITL run for an approval."""
    stmt = (
        select(AgentRunStateRow)
        .where(
            AgentRunStateRow.approval_id == approval_id,
            AgentRunStateRow.status.in_(("paused", "waiting_for_human")),
        )
        .order_by(AgentRunStateRow.updated_at.desc())
    )
    return session.scalars(stmt).first()


def get_latest_run_by_approval(
    session: Session,
    approval_id: str,
) -> AgentRunStateRow | None:
    stmt = (
        select(AgentRunStateRow)
        .where(AgentRunStateRow.approval_id == approval_id)
        .order_by(AgentRunStateRow.updated_at.desc())
    )
    return session.scalars(stmt).first()


def list_agent_run_states(
    session: Session,
    *,
    statuses: list[str] | None = None,
    execution_types: list[str] | None = None,
    recommendation_id: str | None = None,
    recommendation_ids: list[str] | None = None,
    execution_ids: list[str] | None = None,
    user_id: str | None = None,
    correlation_id: str | None = None,
    last_error_code: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AgentRunStateRow]:
    """List durable agent executions (newest first). Column filters only — no envelope load."""
    stmt = select(AgentRunStateRow)
    if statuses:
        stmt = stmt.where(AgentRunStateRow.status.in_(list(statuses)))
    if execution_types:
        stmt = stmt.where(AgentRunStateRow.execution_type.in_(list(execution_types)))
    if recommendation_id:
        stmt = stmt.where(AgentRunStateRow.recommendation_id == recommendation_id)
    if recommendation_ids is not None:
        if not recommendation_ids:
            return []
        stmt = stmt.where(AgentRunStateRow.recommendation_id.in_(list(recommendation_ids)))
    if execution_ids is not None:
        if not execution_ids:
            return []
        stmt = stmt.where(AgentRunStateRow.run_id.in_(list(execution_ids)))
    if user_id:
        stmt = stmt.where(AgentRunStateRow.user_id == user_id)
    if correlation_id:
        stmt = stmt.where(AgentRunStateRow.correlation_id == correlation_id)
    if last_error_code:
        stmt = stmt.where(AgentRunStateRow.last_error_code == last_error_code)
    if started_after is not None:
        stmt = stmt.where(AgentRunStateRow.created_at >= started_after)
    if started_before is not None:
        stmt = stmt.where(AgentRunStateRow.created_at <= started_before)
    safe_limit = max(1, min(int(limit or 100), 500))
    safe_offset = max(0, int(offset or 0))
    stmt = (
        stmt.order_by(AgentRunStateRow.created_at.desc(), AgentRunStateRow.run_id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
    )
    return list(session.scalars(stmt))


def count_agent_run_states(
    session: Session,
    *,
    statuses: list[str] | None = None,
    completed_after: datetime | None = None,
    completed_before: datetime | None = None,
    updated_after: datetime | None = None,
) -> int:
    """Count agent executions matching status / completion window filters."""
    from sqlalchemy import func

    stmt = select(func.count()).select_from(AgentRunStateRow)
    if statuses:
        stmt = stmt.where(AgentRunStateRow.status.in_(list(statuses)))
    if completed_after is not None:
        stmt = stmt.where(AgentRunStateRow.completed_at >= completed_after)
    if completed_before is not None:
        stmt = stmt.where(AgentRunStateRow.completed_at <= completed_before)
    if updated_after is not None:
        stmt = stmt.where(AgentRunStateRow.updated_at >= updated_after)
    return int(session.scalar(stmt) or 0)


def list_completed_agent_durations(
    session: Session,
    *,
    limit: int = 200,
) -> list[tuple[datetime, datetime]]:
    """Return (created_at, completed_at) pairs for recent completed executions."""
    stmt = (
        select(AgentRunStateRow.created_at, AgentRunStateRow.completed_at)
        .where(
            AgentRunStateRow.status == "completed",
            AgentRunStateRow.completed_at.is_not(None),
        )
        .order_by(AgentRunStateRow.completed_at.desc())
        .limit(max(1, min(int(limit or 200), 1000)))
    )
    return [(row[0], row[1]) for row in session.execute(stmt).all() if row[0] and row[1]]


def get_latest_agent_run_by_status(
    session: Session,
    *,
    statuses: list[str],
) -> AgentRunStateRow | None:
    stmt = (
        select(AgentRunStateRow)
        .where(AgentRunStateRow.status.in_(list(statuses)))
        .order_by(AgentRunStateRow.updated_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_audit_events(
    session: Session,
    *,
    recommendation_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
    event_types: list[str] | None = None,
    actor_id: str | None = None,
    actor: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    correlation_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
) -> list[AuditEventRow]:
    stmt = select(AuditEventRow)
    if recommendation_id:
        stmt = stmt.where(AuditEventRow.recommendation_id == recommendation_id)
    if run_id:
        stmt = stmt.where(AuditEventRow.run_id == run_id)
    if event_type:
        stmt = stmt.where(AuditEventRow.event_type == event_type)
    if event_types:
        stmt = stmt.where(AuditEventRow.event_type.in_(event_types))
    if actor_id:
        stmt = stmt.where(AuditEventRow.actor_id == actor_id)
    if actor:
        stmt = stmt.where(
            (AuditEventRow.actor == actor) | (AuditEventRow.actor_id == actor)
        )
    if store_id:
        stmt = stmt.where(AuditEventRow.store_id == store_id)
    if sku:
        stmt = stmt.where(AuditEventRow.sku == sku)
    if correlation_id:
        stmt = stmt.where(AuditEventRow.correlation_id == correlation_id)
    if date_from is not None:
        stmt = stmt.where(AuditEventRow.timestamp >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditEventRow.timestamp <= date_to)
    stmt = stmt.order_by(AuditEventRow.timestamp.desc()).limit(limit)
    return list(session.scalars(stmt))


def get_audit_event(session: Session, event_id: str) -> AuditEventRow | None:
    return session.get(AuditEventRow, event_id)


_SENSITIVE_KEYS = {
    "api_key",
    "openai_api_key",
    "authorization",
    "password",
    "secret",
    "token",
    "access_code",
    "demo_access_code",
    "session_secret",
    "session_token",
    "oidc_client_secret",
    "client_secret",
    "cron_secret",
}


def _sanitize(details: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        lower = key.lower()
        if (
            lower in _SENSITIVE_KEYS
            or "api_key" in lower
            or lower.endswith("_secret")
            or "access_code" in lower
            or "password" in lower
        ):
            cleaned[key] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[key] = _sanitize(value)
        else:
            cleaned[key] = value
    return cleaned

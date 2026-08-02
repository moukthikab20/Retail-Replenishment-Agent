"""Audit event and agent run-state persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AgentRunStateRow, AuditEventRow


def write_audit_event(
    session: Session,
    event_type: str,
    *,
    actor: str = "system",
    actor_role: str | None = None,
    run_id: str | None = None,
    recommendation_id: str | None = None,
    review_id: str | None = None,
    approval_id: str | None = None,
    purchase_order_id: str | None = None,
    details: dict[str, Any] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str:
    event_id = f"EVT-{uuid4().hex[:12]}"
    sanitized = _sanitize(details or {})
    row = AuditEventRow(
        event_id=event_id,
        run_id=run_id,
        recommendation_id=recommendation_id,
        review_id=review_id,
        approval_id=approval_id,
        purchase_order_id=purchase_order_id,
        actor=actor,
        actor_role=actor_role,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        details_json=json.dumps(sanitized, default=str),
        user_id=user_id,
        session_id=session_id,
    )
    session.add(row)
    session.flush()
    return event_id


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
) -> None:
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
        )
        session.add(row)
    else:
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
    session.flush()


def get_agent_run_state(session: Session, run_id: str) -> AgentRunStateRow | None:
    return session.get(AgentRunStateRow, run_id)


def list_audit_events(
    session: Session,
    recommendation_id: str | None = None,
    limit: int = 100,
) -> list[AuditEventRow]:
    stmt = select(AuditEventRow).order_by(AuditEventRow.timestamp.desc()).limit(limit)
    if recommendation_id:
        stmt = (
            select(AuditEventRow)
            .where(AuditEventRow.recommendation_id == recommendation_id)
            .order_by(AuditEventRow.timestamp.desc())
            .limit(limit)
        )
    return list(session.scalars(stmt))


_SENSITIVE_KEYS = {"api_key", "openai_api_key", "authorization", "password", "secret", "token"}


def _sanitize(details: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in _SENSITIVE_KEYS or "api_key" in key.lower():
            cleaned[key] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[key] = _sanitize(value)
        else:
            cleaned[key] = value
    return cleaned

"""Agent Operations — read-only query layer over durable execution state.

Does not start agents, call OpenAI, or mutate business state.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from agent.execution_envelope import AgentExecutionEnvelope, envelope_from_legacy
from agent.execution_states import (
    AUDIT_EXECUTION_CANCELLED,
    AUDIT_EXECUTION_COMPLETED,
    AUDIT_EXECUTION_CREATED,
    AUDIT_EXECUTION_FAILED,
    AUDIT_EXECUTION_PLANNED,
    AUDIT_EXECUTION_RESUMED,
    AUDIT_EXECUTION_STARTED,
    AUDIT_RETRY_SCHEDULED,
    AUDIT_TOOL_COMPLETED,
    AUDIT_TOOL_FAILED,
    AUDIT_TOOL_PAUSED,
    AUDIT_TOOL_REJECTED,
    AUDIT_TOOL_RESUMED,
    AUDIT_TOOL_STARTED,
    AUDIT_WAITING_FOR_HUMAN,
    ExecutionStatus,
)
from config import (
    AGENT_OPS_FAILED_DEGRADED_THRESHOLD,
    AGENT_OPS_FAILED_WINDOW_HOURS,
    AGENT_OPS_LIST_DEFAULT_LIMIT,
    AGENT_OPS_LIST_MAX_LIMIT,
    AGENT_OPS_WAITING_DEGRADED_THRESHOLD,
    REPLENISHMENT_TIMEZONE,
)
from database.connection import get_session, init_db
from database.models import AgentRunStateRow, RecommendationRow
from models.agent_ops import (
    AgentExecutionSummary,
    AgentOperationsMetrics,
    ModelTurnView,
    ToolHistoryView,
)
from repositories import audit_repository

# Active = in-flight technical work (waiting_for_human is its own KPI).
ACTIVE_STATUSES = frozenset(
    {
        ExecutionStatus.CREATED.value,
        ExecutionStatus.PLANNING.value,
        ExecutionStatus.RUNNING.value,
        ExecutionStatus.WAITING_FOR_TOOL.value,
        ExecutionStatus.RETRY_PENDING.value,
    }
)

WAITING_STATUSES = frozenset(
    {
        ExecutionStatus.WAITING_FOR_HUMAN.value,
        ExecutionStatus.PAUSED.value,  # legacy alias
    }
)

AGENT_EXECUTION_AUDIT_TYPES = frozenset(
    {
        AUDIT_EXECUTION_CREATED,
        AUDIT_EXECUTION_PLANNED,
        AUDIT_EXECUTION_STARTED,
        AUDIT_TOOL_STARTED,
        AUDIT_TOOL_COMPLETED,
        AUDIT_TOOL_FAILED,
        AUDIT_RETRY_SCHEDULED,
        AUDIT_WAITING_FOR_HUMAN,
        AUDIT_EXECUTION_RESUMED,
        AUDIT_EXECUTION_COMPLETED,
        AUDIT_EXECUTION_FAILED,
        AUDIT_EXECUTION_CANCELLED,
        AUDIT_TOOL_PAUSED,
        AUDIT_TOOL_RESUMED,
        AUDIT_TOOL_REJECTED,
    }
)

_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|password|secret|token|authorization|access[_-]?code|credential|database_url)",
    re.IGNORECASE,
)

STATUS_LABELS = {
    "created": "Created",
    "planning": "Planning",
    "running": "Running",
    "waiting_for_tool": "Waiting for Tool",
    "waiting_for_human": "Waiting for Human",
    "retry_pending": "Retry Pending",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "paused": "Waiting for Human",
    "rejected": "Rejected",
}

TYPE_LABELS = {
    "recommendation_analysis": "Recommendation Analysis",
    "follow_up": "Follow-up",
    "scenario_analysis": "Scenario Analysis",
    "order_execution": "Order Execution",
}


def status_label(status: str | None) -> str:
    if not status:
        return "—"
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def type_label(execution_type: str | None) -> str:
    if not execution_type:
        return "—"
    return TYPE_LABELS.get(execution_type, execution_type.replace("_", " ").title())


def display_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = str(value)
    if text in {"None", "null", "Null"}:
        return "—"
    return text


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(REPLENISHMENT_TIMEZONE or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime | None) -> str | None:
    aware = _ensure_aware(dt)
    return aware.isoformat() if aware else None


def _duration_seconds(
    created_at: datetime | None,
    completed_at: datetime | None,
    *,
    updated_at: datetime | None = None,
    terminal: bool = False,
) -> float | None:
    start = _ensure_aware(created_at)
    if start is None:
        return None
    end = _ensure_aware(completed_at) if terminal or completed_at else _ensure_aware(
        completed_at or updated_at
    )
    if end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_mapping(value)
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        lower = value.lower()
        if any(
            marker in lower
            for marker in (
                "sk-",
                "Bearer ",
                "password=",
                "api_key=",
                "access_code",
            )
        ):
            return "[redacted]"
    return value


def _sanitize_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if _SENSITIVE_KEY_RE.search(str(key)):
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = _sanitize_value(value)
    return cleaned


def _contains_forbidden(text: str) -> bool:
    lowered = text.lower()
    forbidden = (
        "chain-of-thought",
        "chain_of_thought",
        "hidden reasoning",
        "openai_api_key",
        "cron_secret",
        "demo_access_code",
        "authorization: bearer",
    )
    return any(f in lowered for f in forbidden)


def _row_summary(
    row: AgentRunStateRow,
    *,
    replenishment_run_id: str | None = None,
) -> AgentExecutionSummary:
    terminal = row.status in {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
        ExecutionStatus.CANCELLED.value,
        ExecutionStatus.REJECTED.value,
    }
    return AgentExecutionSummary(
        execution_id=row.run_id,
        execution_type=getattr(row, "execution_type", None),
        status=row.status,
        current_step=getattr(row, "current_step", None),
        next_action=getattr(row, "next_action", None),
        recommendation_id=row.recommendation_id,
        approval_id=row.approval_id,
        replenishment_run_id=replenishment_run_id,
        user_id=row.user_id,
        session_id=row.session_id,
        correlation_id=getattr(row, "correlation_id", None),
        attempt_count=int(getattr(row, "attempt_count", 0) or 0),
        max_attempts=int(getattr(row, "max_attempts", 3) or 3),
        waiting_reason=getattr(row, "waiting_reason", None),
        last_error_code=getattr(row, "last_error_code", None),
        last_error_message=getattr(row, "last_error_message", None),
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
        completed_at=_iso(getattr(row, "completed_at", None)),
        duration_seconds=_duration_seconds(
            row.created_at,
            getattr(row, "completed_at", None),
            updated_at=row.updated_at,
            terminal=terminal,
        ),
        version=int(getattr(row, "version", 1) or 1),
        pending_tool_name=getattr(row, "pending_tool_name", None),
    )


def _recommendation_run_map(
    session,
    recommendation_ids: list[str],
) -> dict[str, str]:
    ids = [r for r in recommendation_ids if r]
    if not ids:
        return {}
    rows = session.scalars(
        select(RecommendationRow).where(RecommendationRow.recommendation_id.in_(ids))
    ).all()
    return {
        r.recommendation_id: r.run_id
        for r in rows
        if r.run_id
    }


def _resolve_run_id_filter(session, run_id: str) -> tuple[list[str] | None, list[str] | None]:
    """Map a RUN-* filter to agent execution ids and/or recommendation ids.

    Avoids mixing batch replenishment audits with agent executions: exact
    agent PK match and/or recommendations belonging to a replenishment run.
    """
    execution = audit_repository.get_agent_run_state(session, run_id)
    rec_ids = list(
        session.scalars(
            select(RecommendationRow.recommendation_id).where(
                RecommendationRow.run_id == run_id
            )
        ).all()
    )
    execution_ids = [run_id] if execution is not None else None
    if execution is None and not rec_ids:
        return [], []
    return execution_ids, (rec_ids or None)


def list_agent_executions(
    *,
    statuses: list[str] | None = None,
    execution_types: list[str] | None = None,
    recommendation_id: str | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    correlation_id: str | None = None,
    last_error_code: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    limit: int | None = None,
    offset: int = 0,
    actor_role: str | None = None,
) -> list[dict[str, Any]]:
    """Newest-first bounded list. Does not parse state_json envelopes."""
    if actor_role is not None:
        from services import auth_service

        auth_service.authorize_agent_operations(actor_role)
    init_db()
    default_limit = AGENT_OPS_LIST_DEFAULT_LIMIT or 100
    max_limit = AGENT_OPS_LIST_MAX_LIMIT or 500
    safe_limit = max(1, min(int(limit if limit is not None else default_limit), max_limit))

    with get_session() as session:
        execution_ids: list[str] | None = None
        recommendation_ids: list[str] | None = None
        if run_id:
            execution_ids, recommendation_ids = _resolve_run_id_filter(session, run_id)
            if execution_ids == [] and recommendation_ids == []:
                return []
            # Prefer exact execution match when present; else recommendation linkage.
            if execution_ids and not recommendation_ids:
                recommendation_ids = None
            elif recommendation_ids and not execution_ids:
                execution_ids = None
            elif execution_ids and recommendation_ids:
                # Union: fetch by either execution id or recommendation belonging to batch.
                by_exec = audit_repository.list_agent_run_states(
                    session,
                    statuses=statuses,
                    execution_types=execution_types,
                    recommendation_id=recommendation_id,
                    execution_ids=execution_ids,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    last_error_code=last_error_code,
                    started_after=started_after,
                    started_before=started_before,
                    limit=safe_limit,
                    offset=offset,
                )
                by_rec = audit_repository.list_agent_run_states(
                    session,
                    statuses=statuses,
                    execution_types=execution_types,
                    recommendation_id=recommendation_id,
                    recommendation_ids=recommendation_ids,
                    user_id=user_id,
                    correlation_id=correlation_id,
                    last_error_code=last_error_code,
                    started_after=started_after,
                    started_before=started_before,
                    limit=safe_limit,
                    offset=0,
                )
                merged: dict[str, AgentRunStateRow] = {r.run_id: r for r in by_exec}
                for r in by_rec:
                    merged[r.run_id] = r
                rows = sorted(
                    merged.values(),
                    key=lambda r: (r.created_at or datetime.min.replace(tzinfo=timezone.utc), r.run_id),
                    reverse=True,
                )[:safe_limit]
                run_map = _recommendation_run_map(
                    session, [r.recommendation_id for r in rows if r.recommendation_id]
                )
                return [
                    _row_summary(
                        r, replenishment_run_id=run_map.get(r.recommendation_id or "")
                    ).to_dict()
                    for r in rows
                ]

        rows = audit_repository.list_agent_run_states(
            session,
            statuses=statuses,
            execution_types=execution_types,
            recommendation_id=recommendation_id,
            recommendation_ids=recommendation_ids,
            execution_ids=execution_ids,
            user_id=user_id,
            correlation_id=correlation_id,
            last_error_code=last_error_code,
            started_after=started_after,
            started_before=started_before,
            limit=safe_limit,
            offset=offset,
        )
        run_map = _recommendation_run_map(
            session, [r.recommendation_id for r in rows if r.recommendation_id]
        )
        return [
            _row_summary(
                r, replenishment_run_id=run_map.get(r.recommendation_id or "")
            ).to_dict()
            for r in rows
        ]


def get_operations_metrics(*, now: datetime | None = None, actor_role: str | None = None) -> dict[str, Any]:
    """Compute operational KPIs from persisted AgentRunStateRow columns only."""
    if actor_role is not None:
        from services import auth_service

        auth_service.authorize_agent_operations(actor_role)
    init_db()
    clock = _ensure_aware(now) or datetime.now(timezone.utc)
    local = clock.astimezone(_tz())
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    with get_session() as session:
        active = audit_repository.count_agent_run_states(
            session, statuses=list(ACTIVE_STATUSES)
        )
        waiting = audit_repository.count_agent_run_states(
            session, statuses=list(WAITING_STATUSES)
        )
        retry_pending = audit_repository.count_agent_run_states(
            session, statuses=[ExecutionStatus.RETRY_PENDING.value]
        )
        failed = audit_repository.count_agent_run_states(
            session, statuses=[ExecutionStatus.FAILED.value]
        )
        completed_today = audit_repository.count_agent_run_states(
            session,
            statuses=[ExecutionStatus.COMPLETED.value],
            completed_after=start_utc,
            completed_before=end_utc,
        )
        durations = audit_repository.list_completed_agent_durations(session, limit=200)
        avg: float | None = None
        if durations:
            secs = []
            for created, completed in durations:
                d = _duration_seconds(created, completed, terminal=True)
                if d is not None:
                    secs.append(d)
            if secs:
                avg = round(sum(secs) / len(secs), 3)

        # Optional tool failure rate from recent completed/failed envelopes — capped.
        tool_failure_rate: float | None = None
        sample = audit_repository.list_agent_run_states(
            session,
            statuses=[
                ExecutionStatus.COMPLETED.value,
                ExecutionStatus.FAILED.value,
                ExecutionStatus.WAITING_FOR_HUMAN.value,
                ExecutionStatus.PAUSED.value,
            ],
            limit=50,
            offset=0,
        )
        tool_total = 0
        tool_failed = 0
        for row in sample:
            try:
                payload = json.loads(row.state_json or "{}")
            except json.JSONDecodeError:
                continue
            history = payload.get("tool_history") or []
            if not isinstance(history, list):
                continue
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                tool_total += 1
                if entry.get("status") == "failed":
                    tool_failed += 1
        if tool_total > 0:
            tool_failure_rate = round(tool_failed / tool_total, 4)

    metrics = AgentOperationsMetrics(
        active_executions=active,
        waiting_for_human=waiting,
        retry_pending=retry_pending,
        failed_executions=failed,
        completed_today=completed_today,
        average_execution_duration_seconds=avg,
        open_hitl_requests=waiting,
        tool_failure_rate=tool_failure_rate,
        timezone=REPLENISHMENT_TIMEZONE or "UTC",
    )
    return metrics.to_dict()


def tool_history_views(envelope: AgentExecutionEnvelope | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(envelope, AgentExecutionEnvelope):
        records = envelope.tool_history
        iterable = [r.model_dump(mode="json") for r in records]
    else:
        iterable = list(envelope.get("tool_history") or [])
    views: list[ToolHistoryView] = []
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        views.append(
            ToolHistoryView(
                tool_call_id=str(entry.get("tool_call_id") or "—"),
                tool_name=str(entry.get("tool_name") or "—"),
                status=str(entry.get("status") or "—"),
                attempt=int(entry.get("attempt_number") or entry.get("attempt") or 1),
                started_at=entry.get("started_at"),
                completed_at=entry.get("completed_at"),
                duration_ms=entry.get("duration_ms"),
                retryable=bool(entry.get("retryable")),
                input_summary=_sanitize_mapping(entry.get("input_summary") or {}),
                output_summary=_sanitize_mapping(entry.get("output_summary") or {}),
                error_code=entry.get("error_code"),
                error_message=entry.get("error_message"),
            )
        )
    return [v.to_dict() for v in views]


def model_turn_views(envelope: AgentExecutionEnvelope | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(envelope, AgentExecutionEnvelope):
        iterable = [r.model_dump(mode="json") for r in envelope.model_turns]
    else:
        iterable = list(envelope.get("model_turns") or [])
    views: list[ModelTurnView] = []
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        # Never surface prompt / reasoning fields even if a legacy blob had them.
        views.append(
            ModelTurnView(
                turn_id=str(entry.get("turn_id") or "—"),
                model_name=entry.get("model_name"),
                status=str(entry.get("status") or "—"),
                started_at=entry.get("started_at"),
                completed_at=entry.get("completed_at"),
                duration_ms=entry.get("duration_ms"),
                input_tokens=entry.get("input_tokens"),
                output_tokens=entry.get("output_tokens"),
                total_tokens=entry.get("total_tokens"),
            )
        )
    return [v.to_dict() for v in views]


def list_agent_execution_audit_events(
    execution_id: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Audit events for one agent execution — never mixes batch RUN-* events by coincidence.

    Requires exact execution_id match on AuditEventRow.run_id AND agent event types.
    """
    init_db()
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            return []
        events = audit_repository.list_audit_events(
            session,
            run_id=execution_id,
            event_types=sorted(AGENT_EXECUTION_AUDIT_TYPES),
            limit=max(1, min(int(limit or 200), 500)),
        )
        # Extra safety: drop events whose run_id does not exactly match.
        out: list[dict[str, Any]] = []
        for ev in events:
            if ev.run_id != execution_id:
                continue
            if ev.event_type not in AGENT_EXECUTION_AUDIT_TYPES:
                continue
            details = {}
            try:
                details = json.loads(ev.details_json or "{}")
            except json.JSONDecodeError:
                details = {}
            out.append(
                {
                    "event_id": ev.event_id,
                    "event_type": ev.event_type,
                    "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
                    "actor": ev.actor or ev.actor_id,
                    "actor_role": ev.actor_role,
                    "recommendation_id": ev.recommendation_id,
                    "approval_id": ev.approval_id,
                    "correlation_id": ev.correlation_id,
                    "run_id": ev.run_id,
                    "details": _sanitize_mapping(details),
                }
            )
        return out


def _timeline_label(event_type: str) -> str:
    mapping = {
        AUDIT_EXECUTION_CREATED: "Execution created",
        AUDIT_EXECUTION_PLANNED: "Plan prepared",
        AUDIT_EXECUTION_STARTED: "Agent started",
        AUDIT_TOOL_STARTED: "Tool started",
        AUDIT_TOOL_COMPLETED: "Tool completed",
        AUDIT_TOOL_FAILED: "Tool failed",
        AUDIT_RETRY_SCHEDULED: "Retry scheduled",
        AUDIT_WAITING_FOR_HUMAN: "Waiting for human",
        AUDIT_EXECUTION_RESUMED: "Execution resumed",
        AUDIT_EXECUTION_COMPLETED: "Execution completed",
        AUDIT_EXECUTION_FAILED: "Execution failed",
        AUDIT_EXECUTION_CANCELLED: "Execution cancelled",
        AUDIT_TOOL_PAUSED: "Tool paused for approval",
        AUDIT_TOOL_RESUMED: "Tool resumed",
        AUDIT_TOOL_REJECTED: "Tool rejected",
    }
    return mapping.get(event_type, event_type.replace("_", " ").title())


def build_execution_timeline(
    *,
    audit_events: list[dict[str, Any]],
    tool_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Chronological timeline. Prefer tool_history for tools; lifecycle from audit."""
    items: list[dict[str, Any]] = []
    tool_audit_types = {
        AUDIT_TOOL_STARTED,
        AUDIT_TOOL_COMPLETED,
        AUDIT_TOOL_FAILED,
    }

    for ev in audit_events:
        et = ev.get("event_type") or ""
        if et in tool_audit_types and tool_history:
            # Deduplicate — tool_history is authoritative when present.
            continue
        details = ev.get("details") or {}
        detail_bits = []
        for key in ("tool_name", "error_code", "reason", "waiting_reason"):
            if details.get(key):
                detail_bits.append(str(details[key]))
        items.append(
            {
                "timestamp": ev.get("timestamp"),
                "label": _timeline_label(et),
                "detail": " · ".join(detail_bits) if detail_bits else None,
                "source": "audit",
                "event_type": et,
            }
        )

    for tool in tool_history:
        started = tool.get("started_at")
        completed = tool.get("completed_at")
        name = tool.get("tool_name") or "tool"
        if started:
            items.append(
                {
                    "timestamp": started,
                    "label": "Tool started",
                    "detail": name,
                    "source": "tool_history",
                    "tool_call_id": tool.get("tool_call_id"),
                }
            )
        if tool.get("status") == "failed":
            items.append(
                {
                    "timestamp": completed or started,
                    "label": "Tool failed",
                    "detail": f"{name}"
                    + (f" · {tool.get('error_code')}" if tool.get("error_code") else ""),
                    "source": "tool_history",
                    "tool_call_id": tool.get("tool_call_id"),
                }
            )
        elif completed or tool.get("status") == "completed":
            dur = tool.get("duration_ms")
            items.append(
                {
                    "timestamp": completed or started,
                    "label": "Tool completed",
                    "detail": f"{name}" + (f" · {dur} ms" if dur is not None else ""),
                    "source": "tool_history",
                    "tool_call_id": tool.get("tool_call_id"),
                }
            )
        elif tool.get("status") == "paused":
            items.append(
                {
                    "timestamp": started,
                    "label": "Waiting for human",
                    "detail": name,
                    "source": "tool_history",
                    "tool_call_id": tool.get("tool_call_id"),
                }
            )

    def _sort_key(item: dict[str, Any]) -> tuple:
        ts = item.get("timestamp") or ""
        return (ts, item.get("label") or "")

    items.sort(key=_sort_key)
    return items


def get_agent_execution_detail(execution_id: str, *, actor_role: str | None = None) -> dict[str, Any] | None:
    """Full detail for one execution — parses envelope only for this id."""
    if actor_role is not None:
        from services import auth_service

        auth_service.authorize_agent_operations(actor_role)
    init_db()
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            return None
        run_map = _recommendation_run_map(
            session, [row.recommendation_id] if row.recommendation_id else []
        )
        summary = _row_summary(
            row,
            replenishment_run_id=run_map.get(row.recommendation_id or ""),
        ).to_dict()

        try:
            payload = json.loads(row.state_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        envelope = envelope_from_legacy(payload if isinstance(payload, dict) else {})
        envelope_dict = envelope.model_dump(mode="json")
        # Strip anything that could look like prompts / CoT / secrets.
        safe_context = _sanitize_mapping(envelope_dict.get("context") or {})
        safe_result = _sanitize_mapping(envelope_dict.get("result") or {})
        for banned in ("prompt", "messages", "chain_of_thought", "reasoning", "system_prompt"):
            safe_context.pop(banned, None)
            safe_result.pop(banned, None)

        tools = tool_history_views(envelope)
        turns = model_turn_views(envelope)
        audits = list_agent_execution_audit_events(execution_id)
        timeline = build_execution_timeline(audit_events=audits, tool_history=tools)

        plan = None
        if envelope.plan is not None:
            plan = {
                "goal": envelope.plan.goal,
                "steps": [
                    {
                        "step_id": s.step_id,
                        "action": s.action,
                        "status": s.status,
                        "tool_name": s.tool_name,
                    }
                    for s in envelope.plan.steps
                ],
            }

        technical = {
            "schema_version": envelope.schema_version,
            "mode": envelope.mode,
            "guards": _sanitize_mapping(envelope.guards or {}),
            "pending_tool_args": _sanitize_mapping(envelope.pending_tool_args or {}),
        }
        dumped = json.dumps(
            {"summary": summary, "context": safe_context, "result": safe_result, "technical": technical},
            default=str,
        )
        if _contains_forbidden(dumped):
            safe_context = {"note": "[redacted sensitive content]"}
            safe_result = {}
            technical = {"schema_version": envelope.schema_version}

        order_lifecycle = None
        try:
            from repositories import order_intent_repository
            from services import order_lifecycle_states as ols

            intent = None
            if row.approval_id:
                intent = order_intent_repository.get_by_approval(session, row.approval_id)
            if intent is None and row.recommendation_id:
                intent = order_intent_repository.get_by_recommendation(
                    session, row.recommendation_id
                )
            if intent is not None:
                order_lifecycle = {
                    "order_intent_id": intent.order_intent_id,
                    "order_status": ols.normalize_status(intent.status),
                    "order_status_label": ols.format_lifecycle_label(intent.status),
                    "erp_provider": intent.erp_provider or "Mock ERP",
                    "erp_transmission_status": ols.transmission_status_for(intent.status),
                    "attempts": intent.attempts,
                    "external_order_id": intent.external_order_id or intent.mock_erp_reference,
                    "acknowledged_at": intent.acknowledged_at.isoformat()
                    if intent.acknowledged_at
                    else None,
                    "last_failure": intent.last_error_message or intent.last_error,
                    "last_error_code": intent.last_error_code,
                    "retry_pending": ols.normalize_status(intent.status) == ols.RETRY_PENDING,
                    "next_retry_at": intent.next_retry_at.isoformat()
                    if intent.next_retry_at
                    else None,
                }
        except Exception:  # noqa: BLE001
            order_lifecycle = None

        memory_summary = None
        raw_ops = safe_context.get("memory_ops") if isinstance(safe_context, dict) else None
        if isinstance(raw_ops, dict):
            kr = raw_ops.get("knowledge_retrieval") or {}
            memory_summary = {
                "memory_retrieved": bool(raw_ops.get("memory_retrieved")),
                "knowledge_sources": list(raw_ops.get("knowledge_sources") or []),
                "retrieved_records": int(raw_ops.get("retrieved_records") or 0),
                "records_by_type": dict(raw_ops.get("records_by_type") or {}),
                "context_size_chars": int(raw_ops.get("context_size_chars") or 0),
                "retrieval_latency_ms": float(raw_ops.get("retrieval_latency_ms") or 0.0),
                "provider_name": raw_ops.get("provider_name"),
                "citations": list(raw_ops.get("citations") or []),
                "knowledge_retrieval": {
                    "method": kr.get("method"),
                    "result_count": kr.get("result_count"),
                    "source_ids": list(kr.get("source_ids") or []),
                    "retrieval_latency_ms": kr.get("retrieval_latency_ms"),
                    "context_size_chars": kr.get("context_size_chars"),
                    "score_range": dict(kr.get("score_range") or {}),
                    "degraded": bool(kr.get("degraded")),
                    "degradation_reason": kr.get("degradation_reason"),
                    "citations": list(kr.get("citations") or []),
                },
            }

        llm_summary = None
        raw_llm = safe_context.get("llm_ops") if isinstance(safe_context, dict) else None
        if isinstance(raw_llm, dict):
            token_usage = raw_llm.get("usage") or raw_llm.get("token_usage") or {}
            if not isinstance(token_usage, dict):
                token_usage = {}
            llm_summary = {
                "provider": raw_llm.get("provider"),
                "model": raw_llm.get("model"),
                "prompt_size_chars": int(raw_llm.get("prompt_size_chars") or 0),
                "context_size_chars": int(raw_llm.get("context_size_chars") or 0),
                "usage": {
                    "input": int(token_usage.get("input") or 0),
                    "output": int(token_usage.get("output") or 0),
                    "total": int(token_usage.get("total") or 0),
                },
                "latency_ms": float(raw_llm.get("latency_ms") or 0.0),
                "tool_calls": list(raw_llm.get("tool_calls") or []),
                "tool_call_count": int(
                    raw_llm.get("tool_call_count")
                    or len(raw_llm.get("tool_calls") or [])
                ),
                "retries": int(raw_llm.get("retries") or 0),
                "finish_reason": raw_llm.get("finish_reason"),
                "validation_ok": raw_llm.get("validation_ok"),
                "validation_errors": list(raw_llm.get("validation_errors") or []),
            }

        planning_summary = None
        raw_plan = safe_context.get("plan_ops") if isinstance(safe_context, dict) else None
        if isinstance(raw_plan, dict):
            planning_summary = {
                "plan_id": raw_plan.get("plan_id"),
                "goal": raw_plan.get("goal"),
                "workflow": raw_plan.get("workflow"),
                "status": raw_plan.get("status"),
                "provider": raw_plan.get("provider"),
                "current_step": raw_plan.get("current_step"),
                "completed_steps": list(raw_plan.get("completed_steps") or []),
                "blocked_steps": list(raw_plan.get("blocked_steps") or []),
                "pending_steps": list(raw_plan.get("pending_steps") or []),
                "parallel_branches": list(raw_plan.get("parallel_branches") or []),
                "step_count": int(raw_plan.get("step_count") or 0),
                "steps": list(raw_plan.get("steps") or []),
                "timeline": list(raw_plan.get("timeline") or []),
                "resume_state": dict(raw_plan.get("resume_state") or {}),
                "task_graph": dict(raw_plan.get("task_graph") or {}),
            }

        decision_summary = None
        raw_decision = (
            safe_context.get("decision_ops") if isinstance(safe_context, dict) else None
        )
        if isinstance(raw_decision, dict):
            decision_summary = {
                "evaluation_id": raw_decision.get("evaluation_id"),
                "status": raw_decision.get("status"),
                "strategy": raw_decision.get("strategy"),
                "winning_action": raw_decision.get("winning_action"),
                "winning_label": raw_decision.get("winning_label"),
                "require_human": bool(raw_decision.get("require_human")),
                "confidence": dict(raw_decision.get("confidence") or {}),
                "risks": list(raw_decision.get("risks") or []),
                "alternatives": list(raw_decision.get("alternatives") or []),
                "policy_references": list(raw_decision.get("policy_references") or []),
                "memory_references": list(raw_decision.get("memory_references") or []),
                "knowledge_references": list(
                    raw_decision.get("knowledge_references") or []
                ),
                "llm_involved": bool(raw_decision.get("llm_involved")),
                "llm_summary": raw_decision.get("llm_summary"),
                "timeline": list(raw_decision.get("timeline") or []),
                "candidate_scores": list(raw_decision.get("candidate_scores") or []),
                "duration_ms": float(raw_decision.get("duration_ms") or 0.0),
                "degraded": bool(raw_decision.get("degraded")),
                "degradation_reason": raw_decision.get("degradation_reason"),
                "narrative": raw_decision.get("narrative"),
                "evidence": list(raw_decision.get("evidence") or []),
                "trade_offs": list(raw_decision.get("trade_offs") or []),
            }

        workflow_summary = None
        raw_wf = (
            safe_context.get("workflow_ops") if isinstance(safe_context, dict) else None
        )
        if isinstance(raw_wf, dict):
            workflow_summary = {
                "workflow_id": raw_wf.get("workflow_id"),
                "plan_id": raw_wf.get("plan_id"),
                "execution_id": raw_wf.get("execution_id"),
                "status": raw_wf.get("status"),
                "current_step": raw_wf.get("current_step"),
                "completed_steps": list(raw_wf.get("completed_steps") or []),
                "waiting_steps": list(raw_wf.get("waiting_steps") or []),
                "failed_steps": list(raw_wf.get("failed_steps") or []),
                "retries": dict(raw_wf.get("retries") or {}),
                "parallel_branches": list(raw_wf.get("parallel_branches") or []),
                "checkpoint": dict(raw_wf.get("checkpoint") or {}),
                "resume_state": dict(raw_wf.get("resume_state") or {}),
                "duration_ms": float(raw_wf.get("duration_ms") or 0.0),
                "business_refs": dict(raw_wf.get("business_refs") or {}),
                "timeline": list(raw_wf.get("timeline") or []),
                "steps": list(raw_wf.get("steps") or []),
                "decision_action": raw_wf.get("decision_action"),
                "require_human": bool(raw_wf.get("require_human")),
                "degraded": bool(raw_wf.get("degraded")),
                "degradation_reason": raw_wf.get("degradation_reason"),
            }

        eventbus_summary = None
        try:
            from eventbus.factory import get_event_bus
            from eventbus.dead_letter import get_dead_letter_queue
            from eventbus.registry import get_registry
            from eventbus.subscriber import ops_events

            bus = get_event_bus()
            eventbus_summary = {
                "provider": bus.provider,
                "enabled": bus.enabled,
                "live_stream": bus.live_stream(limit=25),
                "subscriptions": [s.model_dump() for s in get_registry().list_subscriptions()],
                "dead_letters": [
                    r.model_dump(mode="json")
                    for r in get_dead_letter_queue().list_records()[:20]
                ],
                "dead_letter_stats": get_dead_letter_queue().stats(),
                "worker": bus.worker.health_check(),
                "recent_ops_events": ops_events()[-25:],
            }
        except Exception:  # noqa: BLE001
            eventbus_summary = {"degraded": True}

        return {
            **summary,
            "goal": envelope.goal or None,
            "plan": plan,
            "tool_history": tools,
            "model_turns": turns,
            "context": safe_context,
            "result": safe_result,
            "warnings": list(envelope.warnings or []),
            "requested_action": envelope.requested_action or row.pending_tool_name,
            "required_role": envelope.required_role,
            "order_lifecycle": order_lifecycle,
            "memory": memory_summary,
            "llm": llm_summary,
            "planning": planning_summary,
            "decision": decision_summary,
            "workflow": workflow_summary,
            "eventbus": eventbus_summary,
            "hitl": {
                "waiting": row.status in WAITING_STATUSES,
                "requested_action": envelope.requested_action or row.pending_tool_name,
                "required_role": envelope.required_role,
                "waiting_reason": row.waiting_reason or envelope.waiting_reason,
                "approval_id": row.approval_id,
            },
            "audit_events": audits,
            "timeline": timeline,
            "technical": technical,
        }


def list_waiting_for_human(
    *, limit: int = 50, actor_role: str | None = None
) -> list[dict[str, Any]]:
    """Waiting HITL executions — uses row columns; lightly reads envelope for action/role."""
    if actor_role is not None:
        from services import auth_service

        auth_service.authorize_agent_operations(actor_role)
    init_db()
    with get_session() as session:
        rows = audit_repository.list_agent_run_states(
            session,
            statuses=list(WAITING_STATUSES),
            limit=limit,
            offset=0,
        )
        run_map = _recommendation_run_map(
            session, [r.recommendation_id for r in rows if r.recommendation_id]
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            requested = row.pending_tool_name
            required_role = None
            try:
                payload = json.loads(row.state_json or "{}")
                if isinstance(payload, dict):
                    requested = payload.get("requested_action") or requested
                    required_role = payload.get("required_role")
            except json.JSONDecodeError:
                pass
            summary = _row_summary(
                row, replenishment_run_id=run_map.get(row.recommendation_id or "")
            ).to_dict()
            out.append(
                {
                    **summary,
                    "requested_action": requested,
                    "required_role": required_role,
                    "waiting_since": summary.get("updated_at") or summary.get("created_at"),
                }
            )
        return out


def list_failed_or_retry(
    *, limit: int = 50, actor_role: str | None = None
) -> list[dict[str, Any]]:
    return list_agent_executions(
        statuses=[
            ExecutionStatus.FAILED.value,
            ExecutionStatus.RETRY_PENDING.value,
        ],
        limit=limit,
        actor_role=actor_role,
    )


def export_execution_summary_csv(
    *,
    limit: int = 100,
    statuses: list[str] | None = None,
    actor_role: str | None = None,
) -> str:
    rows = list_agent_executions(statuses=statuses, limit=limit, actor_role=actor_role)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "execution_id",
            "execution_type",
            "status",
            "recommendation_id",
            "approval_id",
            "user_id",
            "started_at",
            "completed_at",
            "duration_seconds",
            "attempt_count",
            "last_error_code",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "execution_id": row.get("execution_id"),
                "execution_type": row.get("execution_type"),
                "status": row.get("status"),
                "recommendation_id": row.get("recommendation_id") or "",
                "approval_id": row.get("approval_id") or "",
                "user_id": row.get("user_id") or "",
                "started_at": row.get("created_at") or "",
                "completed_at": row.get("completed_at") or "",
                "duration_seconds": row.get("duration_seconds")
                if row.get("duration_seconds") is not None
                else "",
                "attempt_count": row.get("attempt_count"),
                "last_error_code": row.get("last_error_code") or "",
            }
        )
    return buf.getvalue()


def get_agent_runtime_health() -> dict[str, Any]:
    """System Health Agent Runtime probe from persisted metrics + queryability."""
    init_db()
    try:
        metrics = get_operations_metrics()
        with get_session() as session:
            last_ok = audit_repository.get_latest_agent_run_by_status(
                session, statuses=[ExecutionStatus.COMPLETED.value]
            )
            last_fail = audit_repository.get_latest_agent_run_by_status(
                session, statuses=[ExecutionStatus.FAILED.value]
            )
            window_start = datetime.now(timezone.utc) - timedelta(
                hours=max(1, AGENT_OPS_FAILED_WINDOW_HOURS)
            )
            recent_failed = audit_repository.count_agent_run_states(
                session,
                statuses=[ExecutionStatus.FAILED.value],
                updated_after=window_start,
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "message": f"Execution persistence/runtime cannot be queried: {exc}",
            "active_executions": None,
            "waiting_executions": None,
            "failed_recent": None,
            "last_successful_execution": None,
            "last_failed_execution": None,
            "thresholds": {
                "failed_window_hours": AGENT_OPS_FAILED_WINDOW_HOURS,
                "failed_degraded_threshold": AGENT_OPS_FAILED_DEGRADED_THRESHOLD,
                "waiting_degraded_threshold": AGENT_OPS_WAITING_DEGRADED_THRESHOLD,
            },
        }

    waiting = int(metrics.get("waiting_for_human") or 0)
    active = int(metrics.get("active_executions") or 0)
    status = "healthy"
    message = "Agent execution persistence is available; recent activity is within thresholds."
    if (
        recent_failed >= AGENT_OPS_FAILED_DEGRADED_THRESHOLD
        or waiting >= AGENT_OPS_WAITING_DEGRADED_THRESHOLD
        or int(metrics.get("retry_pending") or 0) >= AGENT_OPS_FAILED_DEGRADED_THRESHOLD
    ):
        status = "degraded"
        message = (
            f"Elevated failures/retries or waiting backlog "
            f"(failed_in_{AGENT_OPS_FAILED_WINDOW_HOURS}h={recent_failed}, "
            f"waiting={waiting})."
        )

    return {
        "status": status,
        "message": message,
        "active_executions": active,
        "waiting_executions": waiting,
        "failed_recent": recent_failed,
        "retry_pending": metrics.get("retry_pending"),
        "last_successful_execution": (
            {
                "execution_id": last_ok.run_id,
                "updated_at": _iso(last_ok.updated_at),
                "status": last_ok.status,
            }
            if last_ok
            else None
        ),
        "last_failed_execution": (
            {
                "execution_id": last_fail.run_id,
                "updated_at": _iso(last_fail.updated_at),
                "status": last_fail.status,
                "last_error_code": last_fail.last_error_code,
            }
            if last_fail
            else None
        ),
        "thresholds": {
            "failed_window_hours": AGENT_OPS_FAILED_WINDOW_HOURS,
            "failed_degraded_threshold": AGENT_OPS_FAILED_DEGRADED_THRESHOLD,
            "waiting_degraded_threshold": AGENT_OPS_WAITING_DEGRADED_THRESHOLD,
        },
    }


def business_reference(summary: dict[str, Any]) -> str:
    parts: list[str] = []
    if summary.get("recommendation_id"):
        parts.append(str(summary["recommendation_id"]))
    if summary.get("approval_id"):
        parts.append(str(summary["approval_id"]))
    if summary.get("replenishment_run_id"):
        parts.append(str(summary["replenishment_run_id"]))
    return " · ".join(parts) if parts else "—"

"""Durable agent execution engine — Python owns workflow control.

Evolves AgentRunStateRow into a resumable execution record with:
- explicit lifecycle transitions
- versioned optimistic concurrency
- operational plan + tool history envelopes
- HITL pause/resume generalization
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from database.connection import get_session, init_db
from repositories import audit_repository
from services.errors import AppError

from agent.execution_envelope import (
    AgentExecutionEnvelope,
    ModelTurnRecord,
    OperationalPlan,
    ToolExecutionRecord,
    envelope_from_legacy,
    new_tool_call_id,
    plan_for_execution_type,
    utc_iso,
)
from agent.execution_failures import ExecutionFailure, classify_failure
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
    AUDIT_TOOL_STARTED,
    AUDIT_WAITING_FOR_HUMAN,
    ExecutionStatus,
    ExecutionType,
    assert_transition,
    can_transition,
    normalize_status,
)
from agent.tool_registry import get_tool_definition, tool_allows_retry

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_execution_id() -> str:
    return f"RUN-{uuid4().hex[:12]}"


def _new_correlation_id() -> str:
    return f"CORR-{uuid4().hex[:12]}"


def _log_execution(
    event: str,
    *,
    execution_id: str,
    correlation_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    attempt: int | None = None,
    duration_ms: int | None = None,
    status: str | None = None,
    model_name: str | None = None,
    **extra: Any,
) -> None:
    payload = {
        "event": event,
        "execution_id": execution_id,
        "correlation_id": correlation_id,
        "recommendation_id": recommendation_id,
        "approval_id": approval_id,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "attempt": attempt,
        "duration_ms": duration_ms,
        "status": status,
        "model_name": model_name,
        **{k: v for k, v in extra.items() if v is not None},
    }
    # Never log secrets
    for key in list(payload.keys()):
        lk = key.lower()
        if any(s in lk for s in ("api_key", "password", "secret", "token", "access_code")):
            payload[key] = "[redacted]"
    logger.info("agent_execution %s", json.dumps(payload, default=str))


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "execution_id": row.run_id,
        "run_id": row.run_id,
        "recommendation_id": row.recommendation_id,
        "approval_id": row.approval_id,
        "status": row.status,
        "execution_type": getattr(row, "execution_type", None),
        "current_step": getattr(row, "current_step", None),
        "next_action": getattr(row, "next_action", None),
        "attempt_count": int(getattr(row, "attempt_count", 0) or 0),
        "max_attempts": int(getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS),
        "waiting_reason": getattr(row, "waiting_reason", None),
        "last_error_code": getattr(row, "last_error_code", None),
        "last_error_message": getattr(row, "last_error_message", None),
        "correlation_id": getattr(row, "correlation_id", None),
        "version": int(getattr(row, "version", 1) or 1),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": (
            row.completed_at.isoformat()
            if getattr(row, "completed_at", None) is not None
            else None
        ),
        "user_id": row.user_id,
        "session_id": row.session_id,
        "idempotency_key": row.idempotency_key,
        "pending_tool_name": row.pending_tool_name,
        "envelope": _load_envelope(row.state_json),
    }


def _load_envelope(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return AgentExecutionEnvelope().model_dump(mode="json")
    if isinstance(raw, str):
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = raw
    if not isinstance(payload, dict):
        payload = {}
    return envelope_from_legacy(payload).model_dump(mode="json")


def get_execution(execution_id: str) -> dict[str, Any] | None:
    init_db()
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            return None
        return _row_to_dict(row)


def merge_execution_context_fields(
    execution_id: str,
    fields: dict[str, Any],
) -> None:
    """Fail-soft merge into envelope.context without changing execution status."""
    init_db()
    try:
        with get_session() as session:
            row = audit_repository.get_agent_run_state(session, execution_id)
            if row is None:
                return
            try:
                payload = json.loads(row.state_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            ctx = dict(payload.get("context") or {})
            ctx.update(fields)
            payload["context"] = ctx
            row.state_json = json.dumps(payload, default=str)
            session.flush()
    except Exception:  # noqa: BLE001
        logger.exception(
            "merge_execution_context_fields failed execution_id=%s", execution_id
        )


def create_execution(
    *,
    execution_type: str | ExecutionType,
    goal: str,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    actor: str = "system",
    actor_role: str | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    context: dict[str, Any] | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable execution in `created` status with an operational plan."""
    init_db()
    exec_type = str(execution_type)
    if idempotency_key:
        with get_session() as session:
            existing = audit_repository.get_agent_run_by_idempotency_key(
                session, idempotency_key
            )
            if existing is not None:
                return _row_to_dict(existing)

    run_id = execution_id or _new_execution_id()
    corr = correlation_id or _new_correlation_id()
    # Fail-soft memory enrichment — does not alter business workflows.
    try:
        from memory.service import attach_memory_to_execution_context

        enriched_context = attach_memory_to_execution_context(
            dict(context or {}),
            execution_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=(context or {}).get("store_id") if context else None,
            sku=(context or {}).get("sku") if context else None,
            supplier_id=(context or {}).get("supplier_id") if context else None,
            purchase_order_id=(context or {}).get("purchase_order_id")
            if context
            else None,
        )
    except Exception:  # noqa: BLE001
        enriched_context = dict(context or {})

    # Planning Engine creates the task graph — business services never create plans.
    rich_plan = None
    try:
        from planner.service import attach_plan_to_execution_context

        enriched_context, rich_plan = attach_plan_to_execution_context(
            enriched_context,
            goal=goal,
            workflow=str(exec_type),
            execution_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=enriched_context.get("store_id"),
            sku=enriched_context.get("sku"),
            execute=False,
        )
    except Exception:  # noqa: BLE001
        rich_plan = None

    if rich_plan is not None:
        from planner.factory import get_planner

        plan = OperationalPlan.model_validate(
            get_planner().to_operational_plan(rich_plan)
        )
    else:
        plan = plan_for_execution_type(
            exec_type, goal=goal, recommendation_id=recommendation_id
        )

    # Decision Intelligence — between Planner and LLM; fail-soft; never executes actions.
    try:
        from decision.service import attach_decision_to_execution_context

        enriched_context = attach_decision_to_execution_context(
            enriched_context,
            execution_id=run_id,
            goal=goal,
            workflow=str(exec_type),
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=enriched_context.get("store_id"),
            sku=enriched_context.get("sku"),
            actor_role=actor_role,
        )
    except Exception:  # noqa: BLE001
        pass

    # Workflow Automation — durable coordination metadata (fail-soft; no mutation).
    try:
        from workflow.service import attach_workflow_to_execution_context

        enriched_context = attach_workflow_to_execution_context(
            enriched_context,
            execution_id=run_id,
            goal=goal,
            workflow_type=str(exec_type),
            plan_snapshot=enriched_context.get("plan_snapshot"),
            decision_ops=enriched_context.get("decision_ops")
            if isinstance(enriched_context.get("decision_ops"), dict)
            else None,
        )
    except Exception:  # noqa: BLE001
        pass

    # Fail-soft LLM orchestration metadata — Agent Runtime owns model interaction.
    try:
        from llm.service import attach_llm_to_execution_context

        biz = dict(enriched_context.get("business_context") or {})
        if enriched_context.get("decision"):
            biz["decision_recommendation"] = enriched_context.get("decision")
        enriched_context = attach_llm_to_execution_context(
            enriched_context,
            execution_id=run_id,
            workflow=str(exec_type),
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=enriched_context.get("store_id"),
            sku=enriched_context.get("sku"),
            invoke=False,
        )
        if "decision_ops" in enriched_context and isinstance(
            enriched_context.get("llm_ops"), dict
        ):
            enriched_context["llm_ops"]["decision_advisory_context"] = bool(
                enriched_context.get("decision")
            )
    except Exception:  # noqa: BLE001
        pass
    envelope = AgentExecutionEnvelope(
        goal=goal,
        plan=plan,
        current_step=plan.steps[0].step_id if plan.steps else None,
        next_action=plan.steps[0].action if plan.steps else None,
        context=enriched_context,
    )
    with get_session() as session:
        audit_repository.save_agent_run_state(
            session,
            run_id=run_id,
            state_json=envelope.model_dump_json(),
            status=ExecutionStatus.CREATED.value,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            execution_type=exec_type,
            current_step=envelope.current_step,
            next_action=envelope.next_action,
            attempt_count=0,
            max_attempts=max_attempts,
            correlation_id=corr,
            version=1,
        )
        audit_repository.write_audit_event(
            session,
            AUDIT_EXECUTION_CREATED,
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            user_id=user_id,
            session_id=session_id,
            correlation_id=corr,
            details={
                "execution_type": exec_type,
                "goal": goal,
                "version": 1,
            },
        )
        audit_repository.write_audit_event(
            session,
            AUDIT_EXECUTION_PLANNED,
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            correlation_id=corr,
            details={"plan": plan.model_dump(mode="json")},
        )
    _log_execution(
        "created",
        execution_id=run_id,
        correlation_id=corr,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        status=ExecutionStatus.CREATED.value,
    )
    result = get_execution(run_id)
    assert result is not None
    return result


def transition_execution(
    execution_id: str,
    target_status: str | ExecutionStatus,
    *,
    expected_version: int,
    actor: str = "system",
    actor_role: str | None = None,
    waiting_reason: str | None = None,
    next_action: str | None = None,
    current_step: str | None = None,
    error: ExecutionFailure | None = None,
    envelope_patch: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Atomically transition execution status with optimistic concurrency.

    Rejects stale expected_version and illegal transitions.
    """
    init_db()
    target = str(target_status)
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            raise AppError(
                f"No agent execution for {execution_id}",
                code="business_record_missing",
            )
        current_version = int(getattr(row, "version", 1) or 1)
        if current_version != int(expected_version):
            raise AppError(
                f"Stale execution version: expected {expected_version}, "
                f"current {current_version}",
                code="concurrency_conflict",
            )
        assert_transition(row.status, target)

        envelope = envelope_from_legacy(_load_envelope(row.state_json))
        if envelope_patch:
            data = envelope.model_dump(mode="json")
            data.update(envelope_patch)
            envelope = AgentExecutionEnvelope.model_validate(data)

        new_version = current_version + 1
        now = _now()
        completed_at = None
        if target in {
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.REJECTED.value,
        }:
            completed_at = now

        audit_repository.save_agent_run_state(
            session,
            run_id=execution_id,
            state_json=envelope.model_dump_json(),
            status=target,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            pending_tool_name=row.pending_tool_name,
            pending_tool_args=json.loads(row.pending_tool_args_json or "{}"),
            user_id=row.user_id,
            session_id=row.session_id,
            idempotency_key=row.idempotency_key,
            execution_type=getattr(row, "execution_type", None),
            current_step=current_step if current_step is not None else row.current_step,
            next_action=next_action if next_action is not None else row.next_action,
            attempt_count=getattr(row, "attempt_count", 0),
            max_attempts=getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS),
            waiting_reason=waiting_reason
            if waiting_reason is not None
            else getattr(row, "waiting_reason", None),
            last_error_code=error.code if error else getattr(row, "last_error_code", None),
            last_error_message=(
                error.message if error else getattr(row, "last_error_message", None)
            ),
            correlation_id=getattr(row, "correlation_id", None),
            version=new_version,
            completed_at=completed_at,
            expected_version=expected_version,
        )

        event_type = {
            ExecutionStatus.PLANNING.value: AUDIT_EXECUTION_PLANNED,
            ExecutionStatus.RUNNING.value: (
                AUDIT_EXECUTION_RESUMED
                if normalize_status(row.status) == ExecutionStatus.WAITING_FOR_HUMAN
                or row.status == "paused"
                else AUDIT_EXECUTION_STARTED
            ),
            ExecutionStatus.WAITING_FOR_HUMAN.value: AUDIT_WAITING_FOR_HUMAN,
            ExecutionStatus.RETRY_PENDING.value: AUDIT_RETRY_SCHEDULED,
            ExecutionStatus.COMPLETED.value: AUDIT_EXECUTION_COMPLETED,
            ExecutionStatus.FAILED.value: AUDIT_EXECUTION_FAILED,
            ExecutionStatus.CANCELLED.value: AUDIT_EXECUTION_CANCELLED,
            ExecutionStatus.REJECTED.value: "tool_execution_rejected",
        }.get(target, AUDIT_EXECUTION_STARTED)

        audit_repository.write_audit_event(
            session,
            event_type,
            actor=actor,
            actor_role=actor_role,
            run_id=execution_id,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            user_id=row.user_id,
            session_id=row.session_id,
            correlation_id=getattr(row, "correlation_id", None),
            details={
                "from_status": row.status,
                "to_status": target,
                "from_version": current_version,
                "to_version": new_version,
                "waiting_reason": waiting_reason,
                "error": error.to_dict() if error else None,
                **(details or {}),
            },
        )

    _log_execution(
        "transition",
        execution_id=execution_id,
        status=target,
        attempt=None,
    )
    result = get_execution(execution_id)
    assert result is not None
    return result


def start_execution(
    execution_id: str,
    *,
    expected_version: int,
    actor: str = "system",
    actor_role: str | None = None,
) -> dict[str, Any]:
    current = get_execution(execution_id)
    if current is None:
        raise AppError("Execution not found", code="business_record_missing")
    status = current["status"]
    version = current["version"]
    if version != expected_version:
        raise AppError(
            f"Stale execution version: expected {expected_version}, current {version}",
            code="concurrency_conflict",
        )
    if status == ExecutionStatus.CREATED.value:
        transition_execution(
            execution_id,
            ExecutionStatus.PLANNING,
            expected_version=version,
            actor=actor,
            actor_role=actor_role,
        )
        version += 1
    return transition_execution(
        execution_id,
        ExecutionStatus.RUNNING,
        expected_version=version,
        actor=actor,
        actor_role=actor_role,
    )


def record_tool_start(
    execution_id: str,
    *,
    tool_name: str,
    input_summary: dict[str, Any] | None = None,
    expected_version: int | None = None,
    actor: str = "system",
    attempt_number: int = 1,
    tool_call_id: str | None = None,
) -> ToolExecutionRecord:
    """
    Journal tool start. Prefer SDK-supplied tool_call_id when provided.
    Idempotent if the same tool_call_id is already present as started.
    """
    init_db()
    call_id = tool_call_id or new_tool_call_id()
    started = utc_iso()
    record = ToolExecutionRecord(
        tool_call_id=call_id,
        execution_id=execution_id,
        tool_name=tool_name,
        status="started",
        started_at=started,
        input_summary=_sanitize_summary(input_summary or {}),
        attempt_number=attempt_number,
    )
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            raise AppError("Execution not found", code="business_record_missing")
        version = int(getattr(row, "version", 1) or 1)
        if expected_version is not None and version != expected_version:
            raise AppError(
                f"Stale execution version: expected {expected_version}, current {version}",
                code="concurrency_conflict",
            )
        envelope = envelope_from_legacy(_load_envelope(row.state_json))
        history = list(envelope.tool_history)
        for idx, existing in enumerate(history):
            if existing.tool_call_id != call_id:
                continue
            # Same SDK/logical call already present.
            if existing.status == "started":
                return existing
            if existing.status == "paused":
                # HITL resume: reopen the same logical tool_call_id.
                reopened = existing.model_copy(
                    update={
                        "status": "started",
                        "started_at": existing.started_at or started,
                        "completed_at": None,
                        "duration_ms": None,
                        "error_code": None,
                        "error_message": None,
                        "retryable": False,
                        "input_summary": record.input_summary or existing.input_summary,
                        "attempt_number": max(
                            int(existing.attempt_number or 1), attempt_number
                        ),
                    }
                )
                history[idx] = reopened
                envelope.tool_history = history
                if row.status in {
                    ExecutionStatus.WAITING_FOR_HUMAN.value,
                    "paused",
                }:
                    # Human approved: resume into running before tool body executes.
                    assert_transition(row.status, ExecutionStatus.RUNNING)
                    new_status = ExecutionStatus.RUNNING.value
                elif row.status == ExecutionStatus.RUNNING.value:
                    assert_transition(row.status, ExecutionStatus.WAITING_FOR_TOOL)
                    new_status = ExecutionStatus.WAITING_FOR_TOOL.value
                else:
                    new_status = row.status
                audit_repository.save_agent_run_state(
                    session,
                    run_id=execution_id,
                    state_json=envelope.model_dump_json(),
                    status=new_status,
                    recommendation_id=row.recommendation_id,
                    approval_id=row.approval_id,
                    pending_tool_name=tool_name,
                    pending_tool_args=input_summary or {},
                    user_id=row.user_id,
                    session_id=row.session_id,
                    idempotency_key=row.idempotency_key,
                    execution_type=getattr(row, "execution_type", None),
                    current_step=getattr(row, "current_step", None),
                    next_action=tool_name,
                    attempt_count=getattr(row, "attempt_count", 0),
                    max_attempts=getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS),
                    correlation_id=getattr(row, "correlation_id", None),
                    version=version + 1,
                    expected_version=version,
                )
                _log_execution(
                    "tool_reopened",
                    execution_id=execution_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    attempt=reopened.attempt_number,
                    status="started",
                )
                return reopened
            # completed/failed — treat as idempotent no-op for duplicate start
            return existing
        history.append(record)
        envelope.tool_history = history
        if row.status == ExecutionStatus.RUNNING.value:
            assert_transition(row.status, ExecutionStatus.WAITING_FOR_TOOL)
            new_status = ExecutionStatus.WAITING_FOR_TOOL.value
        else:
            new_status = row.status
        audit_repository.save_agent_run_state(
            session,
            run_id=execution_id,
            state_json=envelope.model_dump_json(),
            status=new_status,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            pending_tool_name=tool_name,
            pending_tool_args=input_summary or {},
            user_id=row.user_id,
            session_id=row.session_id,
            idempotency_key=row.idempotency_key,
            execution_type=getattr(row, "execution_type", None),
            current_step=getattr(row, "current_step", None),
            next_action=tool_name,
            attempt_count=getattr(row, "attempt_count", 0),
            max_attempts=getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS),
            correlation_id=getattr(row, "correlation_id", None),
            version=version + 1,
            expected_version=version,
        )
        audit_event_id = f"EVT-{uuid4().hex[:12]}"
        audit_repository.write_audit_event(
            session,
            AUDIT_TOOL_STARTED,
            actor=actor,
            run_id=execution_id,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            correlation_id=getattr(row, "correlation_id", None),
            details={
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "attempt_number": attempt_number,
                "input_summary": record.input_summary,
                "event_id": audit_event_id,
            },
        )
    _log_execution(
        "tool_started",
        execution_id=execution_id,
        tool_name=tool_name,
        tool_call_id=call_id,
        attempt=attempt_number,
        status="started",
    )
    return record


def record_tool_finish(
    execution_id: str,
    *,
    tool_call_id: str,
    status: str,
    output_summary: dict[str, Any] | None = None,
    error: ExecutionFailure | None = None,
    actor: str = "system",
    duration_ms: int | None = None,
) -> dict[str, Any]:
    init_db()
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            raise AppError("Execution not found", code="business_record_missing")
        version = int(getattr(row, "version", 1) or 1)
        envelope = envelope_from_legacy(_load_envelope(row.state_json))
        updated: list[ToolExecutionRecord] = []
        found = False
        already_terminal = False
        for item in envelope.tool_history:
            if item.tool_call_id == tool_call_id:
                found = True
                # completed/failed are terminal. paused may later complete on HITL resume.
                if item.status in {"completed", "failed"}:
                    already_terminal = True
                    updated.append(item)
                    continue
                if item.status == "paused" and status == "paused":
                    already_terminal = True
                    updated.append(item)
                    continue
                updated.append(
                    item.model_copy(
                        update={
                            "status": status,
                            "completed_at": utc_iso(),
                            "duration_ms": duration_ms,
                            "output_summary": _sanitize_summary(output_summary or {}),
                            "error_code": error.code if error else None,
                            "error_message": error.message if error else None,
                            "retryable": bool(error.retryable) if error else False,
                        }
                    )
                )
            else:
                updated.append(item)
        if not found:
            raise AppError(
                f"Unknown tool_call_id {tool_call_id}",
                code="invalid_tool_arguments",
            )
        if already_terminal:
            return _row_to_dict(row)
        envelope.tool_history = updated

        attempt_count = int(getattr(row, "attempt_count", 0) or 0)
        max_attempts = int(
            getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS) or DEFAULT_MAX_ATTEMPTS
        )
        new_status = ExecutionStatus.RUNNING.value
        if status == "failed" and error is not None:
            attempt_count += 1
            meta_retry = tool_allows_retry(
                next(
                    (t.tool_name for t in updated if t.tool_call_id == tool_call_id),
                    "",
                )
            )
            if error.retryable and meta_retry and attempt_count < max_attempts:
                new_status = ExecutionStatus.RETRY_PENDING.value
            else:
                new_status = ExecutionStatus.FAILED.value
        elif status == "paused":
            new_status = ExecutionStatus.WAITING_FOR_HUMAN.value
        elif row.status == ExecutionStatus.WAITING_FOR_TOOL.value:
            assert_transition(row.status, ExecutionStatus.RUNNING)
            new_status = ExecutionStatus.RUNNING.value

        if new_status != row.status:
            assert_transition(row.status, new_status)

        completed_at = _now() if new_status == ExecutionStatus.FAILED.value else None
        audit_repository.save_agent_run_state(
            session,
            run_id=execution_id,
            state_json=envelope.model_dump_json(),
            status=new_status,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            pending_tool_name=row.pending_tool_name if status == "paused" else None,
            pending_tool_args=json.loads(row.pending_tool_args_json or "{}"),
            user_id=row.user_id,
            session_id=row.session_id,
            idempotency_key=row.idempotency_key,
            execution_type=getattr(row, "execution_type", None),
            current_step=getattr(row, "current_step", None),
            next_action=getattr(row, "next_action", None),
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            waiting_reason=getattr(row, "waiting_reason", None),
            last_error_code=error.code if error else None,
            last_error_message=error.message if error else None,
            correlation_id=getattr(row, "correlation_id", None),
            version=version + 1,
            completed_at=completed_at,
            expected_version=version,
        )
        event = AUDIT_TOOL_COMPLETED if status == "completed" else AUDIT_TOOL_FAILED
        if status == "paused":
            event = AUDIT_TOOL_PAUSED
        if new_status == ExecutionStatus.RETRY_PENDING.value:
            audit_repository.write_audit_event(
                session,
                AUDIT_RETRY_SCHEDULED,
                actor=actor,
                run_id=execution_id,
                recommendation_id=row.recommendation_id,
                correlation_id=getattr(row, "correlation_id", None),
                details={
                    "tool_call_id": tool_call_id,
                    "attempt_count": attempt_count,
                    "max_attempts": max_attempts,
                    "error": error.to_dict() if error else None,
                },
            )
        audit_repository.write_audit_event(
            session,
            event,
            actor=actor,
            run_id=execution_id,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            correlation_id=getattr(row, "correlation_id", None),
            details={
                "tool_call_id": tool_call_id,
                "status": status,
                "output_summary": _sanitize_summary(output_summary or {}),
                "error": error.to_dict() if error else None,
                "duration_ms": duration_ms,
            },
        )
    _log_execution(
        "tool_finished",
        execution_id=execution_id,
        tool_call_id=tool_call_id,
        status=status,
        duration_ms=duration_ms,
    )
    result = get_execution(execution_id)
    assert result is not None
    return result


def mark_waiting_for_human(
    execution_id: str,
    *,
    expected_version: int,
    reason: str,
    requested_action: str,
    required_role: str | None = None,
    pending_tool_name: str | None = None,
    pending_tool_args: dict[str, Any] | None = None,
    envelope_patch: dict[str, Any] | None = None,
    actor: str = "system",
    actor_role: str | None = None,
) -> dict[str, Any]:
    patch = {
        "requested_action": requested_action,
        "required_role": required_role,
        "waiting_reason": reason,
        "pending_tool_name": pending_tool_name,
        "pending_tool_args": pending_tool_args or {},
        **(envelope_patch or {}),
    }
    return transition_execution(
        execution_id,
        ExecutionStatus.WAITING_FOR_HUMAN,
        expected_version=expected_version,
        actor=actor,
        actor_role=actor_role,
        waiting_reason=reason,
        next_action="await_human",
        envelope_patch=patch,
        details={"requested_action": requested_action, "required_role": required_role},
    )


def resume_agent_execution(
    execution_id: str,
    *,
    actor: str,
    actor_role: str,
    resume_payload: dict[str, Any] | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    """
    General HITL resume. Order-specific PO creation still delegated to runner.

    Idempotent for already-completed / already-rejected executions.
    """
    from services import auth_service

    init_db()
    resume_payload = resume_payload or {}
    current = get_execution(execution_id)
    if current is None:
        raise AppError(
            f"No agent execution for {execution_id}",
            code="business_record_missing",
        )

    status = current["status"]
    version = current["version"]
    if expected_version is not None and version != expected_version:
        raise AppError(
            f"Stale execution version: expected {expected_version}, current {version}",
            code="concurrency_conflict",
        )

    # Idempotent terminals
    if status == ExecutionStatus.COMPLETED.value:
        return {
            "status": "completed",
            "execution_id": execution_id,
            "run_id": execution_id,
            "mode": "idempotent_reload",
            "message": "Execution already completed.",
            "envelope": current["envelope"],
            "approval_id": current.get("approval_id"),
            "recommendation_id": current.get("recommendation_id"),
        }
    if status in {ExecutionStatus.REJECTED.value, "rejected"}:
        return {
            "status": "rejected",
            "execution_id": execution_id,
            "run_id": execution_id,
            "message": "Execution was previously rejected.",
        }

    waiting = normalize_status(status) == ExecutionStatus.WAITING_FOR_HUMAN or status == "paused"
    if not waiting:
        raise AppError(
            f"Execution is not waiting for human (status={status}).",
            code="invalid_state_transition",
        )

    envelope = current.get("envelope") or {}
    required_role = envelope.get("required_role")
    auth_service.authorize_hitl_resume(actor_role, required_role)

    approve = bool(resume_payload.get("approve", True))
    if not approve:
        return transition_execution(
            execution_id,
            ExecutionStatus.REJECTED,
            expected_version=version,
            actor=actor,
            actor_role=actor_role,
            details={"approved": False},
        )

    # Order execution: reuse existing order HITL resume path (authoritative PO logic).
    exec_type = current.get("execution_type") or ""
    pending_tool = current.get("pending_tool_name") or (
        current.get("envelope") or {}
    ).get("pending_tool_name")
    if exec_type == ExecutionType.ORDER_EXECUTION.value or pending_tool == "create_mock_purchase_order":
        from agent.runner import resume_order_run

        # Map legacy paused if needed — resume_order_run still understands paused.
        # Ensure row status is paused OR waiting_for_human for order resume.
        order_result = resume_order_run(
            run_id=execution_id,
            approve=True,
            actor=actor,
            actor_role=actor_role,
        )
        # Align status to completed via engine if order path marked completed.
        refreshed = get_execution(execution_id)
        return {
            **order_result,
            "execution_id": execution_id,
            "execution": refreshed,
        }

    # Generic resume: transition back to running then completed (no business mutation).
    running = transition_execution(
        execution_id,
        ExecutionStatus.RUNNING,
        expected_version=version,
        actor=actor,
        actor_role=actor_role,
        details={"resume_payload_keys": list(resume_payload.keys())},
    )
    return transition_execution(
        running["execution_id"],
        ExecutionStatus.COMPLETED,
        expected_version=running["version"],
        actor=actor,
        actor_role=actor_role,
        details={"generic_resume": True},
    )


def complete_execution(
    execution_id: str,
    *,
    expected_version: int,
    result: dict[str, Any] | None = None,
    actor: str = "system",
    actor_role: str | None = None,
) -> dict[str, Any]:
    return transition_execution(
        execution_id,
        ExecutionStatus.COMPLETED,
        expected_version=expected_version,
        actor=actor,
        actor_role=actor_role,
        envelope_patch={"result": result or {}},
    )


def fail_execution(
    execution_id: str,
    *,
    expected_version: int,
    error: ExecutionFailure,
    actor: str = "system",
    actor_role: str | None = None,
) -> dict[str, Any]:
    return transition_execution(
        execution_id,
        ExecutionStatus.FAILED,
        expected_version=expected_version,
        actor=actor,
        actor_role=actor_role,
        error=error,
    )


def schedule_retry(
    execution_id: str,
    *,
    expected_version: int,
    error: ExecutionFailure,
    actor: str = "system",
) -> dict[str, Any]:
    if not error.retryable:
        return fail_execution(
            execution_id,
            expected_version=expected_version,
            error=error,
            actor=actor,
        )
    current = get_execution(execution_id)
    if current is None:
        raise AppError("Execution not found", code="business_record_missing")
    if current["attempt_count"] >= current["max_attempts"]:
        return fail_execution(
            execution_id,
            expected_version=expected_version,
            error=classify_failure(
                code=error.code,
                attempt=current["attempt_count"],
            ),
            actor=actor,
        )
    return transition_execution(
        execution_id,
        ExecutionStatus.RETRY_PENDING,
        expected_version=expected_version,
        actor=actor,
        error=error,
    )


def _sanitize_summary(value: Any) -> Any:
    sensitive = frozenset(
        {"api_key", "openai_api_key", "authorization", "password", "secret", "token", "access_code"}
    )
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in sensitive or "api_key" in str(key).lower():
                out[key] = "[redacted]"
            else:
                out[key] = _sanitize_summary(item)
        return out
    if isinstance(value, list):
        return [_sanitize_summary(v) for v in value]
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "…"
    return value


def record_model_turn_start(
    execution_id: str,
    *,
    turn_id: str | None = None,
    model_name: str | None = None,
    actor: str = "system",
) -> ModelTurnRecord:
    init_db()
    tid = turn_id or f"MT-{uuid4().hex[:12]}"
    turn = ModelTurnRecord(
        turn_id=tid,
        execution_id=execution_id,
        started_at=utc_iso(),
        model_name=model_name,
        status="started",
    )
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            raise AppError("Execution not found", code="business_record_missing")
        version = int(getattr(row, "version", 1) or 1)
        envelope = envelope_from_legacy(_load_envelope(row.state_json))
        turns = list(getattr(envelope, "model_turns", None) or [])
        turns.append(turn)
        envelope.model_turns = turns
        audit_repository.save_agent_run_state(
            session,
            run_id=execution_id,
            state_json=envelope.model_dump_json(),
            status=row.status,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            pending_tool_name=row.pending_tool_name,
            pending_tool_args=json.loads(row.pending_tool_args_json or "{}"),
            user_id=row.user_id,
            session_id=row.session_id,
            idempotency_key=row.idempotency_key,
            execution_type=getattr(row, "execution_type", None),
            current_step=getattr(row, "current_step", None),
            next_action=getattr(row, "next_action", None),
            attempt_count=getattr(row, "attempt_count", 0),
            max_attempts=getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS),
            correlation_id=getattr(row, "correlation_id", None),
            version=version + 1,
            expected_version=version,
        )
    _log_execution(
        "model_turn_started",
        execution_id=execution_id,
        status="started",
        model_name=model_name,
        extra_turn_id=tid,
    )
    return turn


def record_model_turn_end(
    execution_id: str,
    *,
    turn_id: str,
    model_name: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    status: str = "completed",
    duration_ms: int | None = None,
) -> dict[str, Any]:
    init_db()
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, execution_id)
        if row is None:
            raise AppError("Execution not found", code="business_record_missing")
        version = int(getattr(row, "version", 1) or 1)
        envelope = envelope_from_legacy(_load_envelope(row.state_json))
        turns: list[ModelTurnRecord] = []
        found = False
        for turn in getattr(envelope, "model_turns", None) or []:
            if turn.turn_id == turn_id:
                found = True
                turns.append(
                    turn.model_copy(
                        update={
                            "completed_at": utc_iso(),
                            "duration_ms": duration_ms,
                            "model_name": model_name or turn.model_name,
                            "status": status,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                        }
                    )
                )
            else:
                turns.append(turn)
        if not found:
            turns.append(
                ModelTurnRecord(
                    turn_id=turn_id,
                    execution_id=execution_id,
                    completed_at=utc_iso(),
                    duration_ms=duration_ms,
                    model_name=model_name,
                    status=status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
            )
        envelope.model_turns = turns
        audit_repository.save_agent_run_state(
            session,
            run_id=execution_id,
            state_json=envelope.model_dump_json(),
            status=row.status,
            recommendation_id=row.recommendation_id,
            approval_id=row.approval_id,
            pending_tool_name=row.pending_tool_name,
            pending_tool_args=json.loads(row.pending_tool_args_json or "{}"),
            user_id=row.user_id,
            session_id=row.session_id,
            idempotency_key=row.idempotency_key,
            execution_type=getattr(row, "execution_type", None),
            current_step=getattr(row, "current_step", None),
            next_action=getattr(row, "next_action", None),
            attempt_count=getattr(row, "attempt_count", 0),
            max_attempts=getattr(row, "max_attempts", DEFAULT_MAX_ATTEMPTS),
            correlation_id=getattr(row, "correlation_id", None),
            version=version + 1,
            expected_version=version,
        )
    _log_execution(
        "model_turn_ended",
        execution_id=execution_id,
        status=status,
        duration_ms=duration_ms,
        model_name=model_name,
    )
    result = get_execution(execution_id)
    assert result is not None
    return result


def reconcile_unfinished_tools(
    execution_id: str,
    *,
    actor: str = "system",
    error_code: str = "tool_interrupted",
    error_message: str = "Tool left unfinished when Runner exited",
) -> list[str]:
    """
    Mark any tool_history entries still in `started` as failed.
    Returns reconciled tool_call_ids. Idempotent / no double-fail.
    """
    init_db()
    reconciled: list[str] = []
    current = get_execution(execution_id)
    if current is None:
        return reconciled
    history = (current.get("envelope") or {}).get("tool_history") or []
    for item in history:
        if item.get("status") != "started":
            continue
        tid = item.get("tool_call_id")
        if not tid:
            continue
        try:
            record_tool_finish(
                execution_id,
                tool_call_id=str(tid),
                status="failed",
                error=classify_failure(
                    code=error_code,
                    attempt=int(item.get("attempt_number") or 1),
                    tool_name=item.get("tool_name"),
                ),
                actor=actor,
            )
            # classify_failure message may not carry our message — patch via details
            reconciled.append(str(tid))
        except Exception:  # noqa: BLE001
            logger.exception("reconcile unfinished tool %s failed", tid)
    if reconciled:
        _log_execution(
            "tools_reconciled",
            execution_id=execution_id,
            status="failed",
            reconciled_count=len(reconciled),
        )
    return reconciled


def try_complete_execution(
    execution_id: str,
    *,
    result: dict[str, Any] | None = None,
    actor: str = "system",
) -> dict[str, Any] | None:
    """Best-effort complete if execution is still active. Never raises."""
    try:
        current = get_execution(execution_id)
        if current is None:
            return None
        if current["status"] in {
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.CANCELLED.value,
            ExecutionStatus.REJECTED.value,
            "rejected",
        }:
            return current
        if current["status"] in {
            ExecutionStatus.RUNNING.value,
            ExecutionStatus.WAITING_FOR_TOOL.value,
            ExecutionStatus.PLANNING.value,
            ExecutionStatus.RETRY_PENDING.value,
            ExecutionStatus.CREATED.value,
        }:
            return complete_execution(
                execution_id,
                expected_version=current["version"],
                result=result,
                actor=actor,
            )
    except Exception:  # noqa: BLE001
        logger.exception("try_complete_execution failed for %s", execution_id)
    return None


# Public re-exports for tests
__all__ = [
    "can_transition",
    "complete_execution",
    "create_execution",
    "fail_execution",
    "get_execution",
    "mark_waiting_for_human",
    "record_tool_finish",
    "record_tool_start",
    "resume_agent_execution",
    "schedule_retry",
    "start_execution",
    "transition_execution",
    "try_complete_execution",
]

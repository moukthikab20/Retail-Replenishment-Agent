"""Agent run helpers for Streamlit, follow-up, and HITL resume."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

from agents import (
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    ModelBehaviorError,
    OutputGuardrailTripwireTriggered,
    RunConfig,
    RunState,
    Runner,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
    ToolTimeoutError,
    set_tracing_disabled,
)
from agents.tracing import set_tracing_export_api_key
from pydantic import ValidationError

from agent.context import ReplenishmentRunContext
from agent.hitl import (
    build_pause_envelope,
    envelope_to_json,
    parse_state_envelope,
    validate_resume_guards,
)
from agent.orchestrator import (
    analysis_max_turns,
    build_follow_up_agent,
    build_replenishment_agent,
    follow_up_max_turns,
)
from agent.schemas import (
    FollowUpAnswer,
    FollowUpQuestionType,
    OrderExecutionResult,
    ReplenishmentAgentDecision,
)
from agent.follow_up_guardrails import (
    FOLLOW_UP_PROHIBITED_NEXT_ACTION,
    detect_prohibited_follow_up,
)
from agent.sessions import follow_up_session_id, get_follow_up_session
from config import (
    AGENT_TRACING_DISABLED,
    OPENAI_API_KEY,
    TRACE_INCLUDE_SENSITIVE_DATA,
    WORKFLOW_ANALYSIS,
    WORKFLOW_FOLLOW_UP,
    WORKFLOW_ORDER,
)
from database.connection import get_session, init_db
from repositories import audit_repository, purchase_order_repository
from services import (
    approval_service,
    inventory_service,
    recommendation_service,
    scenario_service,
)
from services.errors import AppError

logger = logging.getLogger(__name__)

_GUARDRAIL_ERRORS = (
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
)


def _configure_tracing() -> None:
    """Enable tracing unless disabled by config or missing API key."""
    if AGENT_TRACING_DISABLED or not OPENAI_API_KEY:
        set_tracing_disabled(True)
        return
    set_tracing_disabled(False)
    try:
        set_tracing_export_api_key(OPENAI_API_KEY)
    except Exception:
        pass
    if not TRACE_INCLUDE_SENSITIVE_DATA:
        logger.debug("TRACE_INCLUDE_SENSITIVE_DATA disabled")


def _build_run_config(
    *,
    workflow_name: str,
    group_id: str | None,
    trace_metadata: dict[str, Any] | None,
) -> RunConfig:
    return RunConfig(
        workflow_name=workflow_name,
        tracing_disabled=AGENT_TRACING_DISABLED or not OPENAI_API_KEY,
        trace_include_sensitive_data=TRACE_INCLUDE_SENSITIVE_DATA,
        group_id=group_id,
        trace_metadata=trace_metadata,
    )


def _make_context(
    *,
    run_id: str,
    user_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    actor: str = "agent",
    actor_role: str | None = None,
    recommendation_id: str | None = None,
) -> ReplenishmentRunContext:
    return ReplenishmentRunContext(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=conversation_id,
        actor=actor,
        actor_role=actor_role,
        recommendation_id=recommendation_id,
    )


def follow_up_conversation_id(
    recommendation_id: str,
    session_id: str | None = None,
    *,
    user_id: str | None = None,
) -> str:
    """
    Stable follow-up session key.

    Canonical form is replenishment:{user_id}:{recommendation_id}.
    session_id is ignored for identity (kept for call-site compatibility).
    """
    del session_id  # conversational identity is user+recommendation only
    return follow_up_session_id(user_id or "anonymous", recommendation_id)


def _execute_runner(
    agent: Any,
    input_payload: Any,
    *,
    context: ReplenishmentRunContext | None = None,
    max_turns: int | None = None,
    run_config: RunConfig | None = None,
    session: Any | None = None,
) -> Any:
    """
    Run the agent without calling Runner.run_sync inside an active event loop.

    Streamlit / async hosts may already own a loop; in that case we execute
    Runner.run in a worker thread with its own event loop.
    """
    turns = max_turns if max_turns is not None else analysis_max_turns()
    kwargs: dict[str, Any] = {
        "context": context,
        "max_turns": turns,
        "run_config": run_config,
    }
    if session is not None:
        kwargs["session"] = session

    try:
        asyncio.get_running_loop()
        in_running_loop = True
    except RuntimeError:
        in_running_loop = False

    if in_running_loop:
        def _in_thread() -> Any:
            return asyncio.run(Runner.run(agent, input_payload, **kwargs))

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_in_thread).result()

    return Runner.run_sync(agent, input_payload, **kwargs)


def analyze_replenishment(
    store_id: str,
    sku: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    actor: str = "agent",
    actor_role: str | None = None,
) -> dict[str, Any]:
    """
    Analyze replenishment for store/SKU.

    Uses the OpenAI Agents SDK when OPENAI_API_KEY is set; otherwise runs the
    same deterministic service pipeline and returns a structured decision.
    Authoritative recommendation rows are persisted in the database.
    """
    init_db()
    _configure_tracing()
    run_id = f"RUN-{uuid4().hex[:12]}"

    if not OPENAI_API_KEY:
        try:
            return _deterministic_analysis(
                store_id,
                sku,
                run_id,
                user_id=user_id,
                session_id=session_id,
                actor=actor,
            )
        except (AppError, ValueError) as exc:
            return _analysis_domain_error(
                run_id=run_id,
                store_id=store_id,
                sku=sku,
                exc=exc,
            )

    agent = build_replenishment_agent()
    prompt = (
        f"Analyze replenishment for store_id={store_id} and sku={sku}. "
        "Follow the required analysis tool sequence. Use tools for all facts. "
        "Save a recommendation. Do not create an approval or purchase order. "
        "Return ReplenishmentAgentDecision with an appropriate next_action."
    )
    context = _make_context(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=session_id,
        actor=actor,
        actor_role=actor_role,
    )
    run_config = _build_run_config(
        workflow_name=WORKFLOW_ANALYSIS,
        group_id=session_id or user_id or run_id,
        trace_metadata={
            "run_id": run_id,
            "store_id": store_id,
            "sku": sku,
            "user_id": user_id,
            "session_id": session_id,
            "workflow": WORKFLOW_ANALYSIS,
        },
    )
    try:
        result = _execute_runner(
            agent,
            prompt,
            context=context,
            max_turns=analysis_max_turns(),
            run_config=run_config,
        )
    except Exception as exc:  # noqa: BLE001
        return _map_run_exception(
            exc,
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            kind="analysis",
        )

    if result.interruptions:
        state = result.to_state()
        _persist_run_state(run_id, state, recommendation_id=None, status="paused")
        return {
            "status": "paused",
            "run_id": run_id,
            "interruptions": [str(i) for i in result.interruptions],
            "message": "Agent paused for tool approval unexpectedly during analysis.",
        }

    return _coerce_analysis_output(
        result.final_output,
        run_id=run_id,
        store_id=store_id,
        sku=sku,
        user_id=user_id,
        session_id=session_id,
        actor=actor,
    )


# Backward-compatible alias used by older pages/tests.
run_analysis = analyze_replenishment


def answer_follow_up(
    recommendation_id: str,
    question: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    actor: str = "agent",
    actor_role: str | None = None,
) -> dict[str, Any]:
    """
    Answer a follow-up question about a saved recommendation.

    Session identity is user_id + recommendation_id (conversational memory only).
    Runs the single Retail Replenishment Agent with FOLLOW_UP_INSTRUCTIONS /
    FOLLOW_UP_TOOLS and a finite follow-up turn budget. Does not create approvals
    or purchase orders. Returns a FollowUpAnswer-shaped dict (plus run metadata).
    """
    init_db()
    _configure_tracing()
    run_id = f"RUN-{uuid4().hex[:12]}"
    effective_user_id = (user_id or "").strip() or "anonymous"
    question = (question or "").strip()
    inferred_question_type = _infer_follow_up_question_type(question)
    # SDK Session only — do not also pass conversation_id / previous_response_id.
    follow_up_session_key = follow_up_session_id(effective_user_id, recommendation_id)
    max_turns = follow_up_max_turns()

    if not question:
        return _follow_up_error(
            run_id=run_id,
            recommendation_id=recommendation_id,
            error_code="empty_question",
            message="Enter a follow-up question about this recommendation.",
            unresolved=["question is required"],
            question_type="general",
            conversation_id=follow_up_session_key,
        )

    policy_block = detect_prohibited_follow_up(question)
    if policy_block:
        return _follow_up_prohibited(
            run_id=run_id,
            recommendation_id=recommendation_id,
            policy_block=policy_block,
            conversation_id=follow_up_session_key,
        )

    try:
        rec = recommendation_service.get_recommendation(recommendation_id)
    except ValueError:
        return _follow_up_error(
            run_id=run_id,
            recommendation_id=recommendation_id,
            error_code="missing_recommendation",
            message="No saved recommendation was found for this follow-up question.",
            unresolved=["recommendation_id not found"],
            question_type="missing_data",
            conversation_id=follow_up_session_key,
        )
    except Exception as exc:  # noqa: BLE001
        return _follow_up_error(
            run_id=run_id,
            recommendation_id=recommendation_id,
            error_code="recommendation_lookup_failed",
            message="Could not load the saved recommendation.",
            unresolved=[type(exc).__name__],
            question_type="missing_data",
            conversation_id=follow_up_session_key,
        )

    # Deterministic scenario routing always available (model must not invent impact).
    scenario_answer = _try_deterministic_scenario_follow_up(
        run_id=run_id,
        recommendation=rec,
        question=question,
        conversation_id=follow_up_session_key,
    )
    if scenario_answer is not None:
        return scenario_answer

    if not OPENAI_API_KEY:
        return _deterministic_follow_up(
            run_id=run_id,
            recommendation=rec,
            question=question,
            conversation_id=follow_up_session_key,
        )

    agent = build_follow_up_agent()
    prompt = (
        f"Follow-up about saved recommendation_id={recommendation_id}. "
        f"User question: {question}\n"
        "Follow FOLLOW_UP_INSTRUCTIONS. Return FollowUpAnswer only."
    )
    context = _make_context(
        run_id=run_id,
        user_id=effective_user_id,
        session_id=session_id,
        conversation_id=follow_up_session_key,
        actor=actor,
        actor_role=actor_role,
        recommendation_id=recommendation_id,
    )
    run_config = _build_run_config(
        workflow_name=WORKFLOW_FOLLOW_UP,
        group_id=follow_up_session_key,
        trace_metadata={
            "workflow_name": WORKFLOW_FOLLOW_UP,
            "run_id": run_id,
            "recommendation_id": recommendation_id,
            "user_id": effective_user_id,
            "session_id": session_id,
            "follow_up_session_id": follow_up_session_key,
            "question_type": inferred_question_type,
            "workflow": WORKFLOW_FOLLOW_UP,
            "max_turns": max_turns,
        },
    )
    # Conversational memory only — keyed by user_id + recommendation_id.
    sdk_session = get_follow_up_session(effective_user_id, recommendation_id)
    try:
        result = _execute_runner(
            agent,
            prompt,
            context=context,
            max_turns=max_turns,
            run_config=run_config,
            session=sdk_session,
        )
    except Exception as exc:  # noqa: BLE001
        prohibited = _follow_up_guardrail_prohibition(exc)
        if prohibited is not None:
            return _follow_up_prohibited(
                run_id=run_id,
                recommendation_id=recommendation_id,
                policy_block=prohibited,
                conversation_id=follow_up_session_key,
                verified=_verified_facts_from_recommendation(rec),
            )
        mapped = _map_run_exception(
            exc,
            run_id=run_id,
            store_id=str(rec.get("store_id", "")),
            sku=str(rec.get("sku", "")),
            kind="follow_up",
        )
        return _follow_up_error(
            run_id=run_id,
            recommendation_id=recommendation_id,
            error_code=mapped.get("error_code", "follow_up_failed"),
            message=mapped.get("message", "Follow-up could not be completed."),
            unresolved=[mapped.get("message", "Follow-up failed")],
            verified=_verified_facts_from_recommendation(rec),
            question_type=inferred_question_type,
            conversation_id=follow_up_session_key,
        )

    output = result.final_output
    try:
        if isinstance(output, FollowUpAnswer):
            answer_model = output
        elif isinstance(output, dict):
            answer_model = FollowUpAnswer.model_validate(output)
        else:
            raise ValueError("Follow-up output was not structured")
        # Follow-up never mutates business state, even if the model claims otherwise.
        payload = answer_model.model_copy(
            update={"can_change_business_state": False}
        ).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError):
        return _follow_up_error(
            run_id=run_id,
            recommendation_id=recommendation_id,
            error_code="malformed_structured_output",
            message="The follow-up response was not valid structured output.",
            unresolved=["malformed FollowUpAnswer"],
            verified=_verified_facts_from_recommendation(rec),
            question_type=inferred_question_type,
            conversation_id=follow_up_session_key,
        )

    payload["status"] = "completed"
    payload["run_id"] = run_id
    payload["conversation_id"] = follow_up_session_key
    payload["follow_up_session_id"] = follow_up_session_key
    payload["can_change_business_state"] = False
    payload["mode"] = "agent"
    return payload


def get_pending_order_flow(approval_id: str) -> dict[str, Any] | None:
    """Reload paused HITL work from DB so browser refresh does not lose it."""
    init_db()
    with get_session() as session:
        existing_po = purchase_order_repository.get_purchase_order_by_approval(
            session, approval_id
        )
        if existing_po is not None:
            latest = audit_repository.get_latest_run_by_approval(session, approval_id)
            return {
                "status": "completed",
                "run_id": latest.run_id if latest else None,
                "purchase_order": existing_po.model_dump(mode="json"),
                "mode": "reloaded",
            }
        row = audit_repository.get_paused_run_by_approval(session, approval_id)
        if row is None:
            return None
        envelope = parse_state_envelope(row.state_json)
        return {
            "status": "paused",
            "run_id": row.run_id,
            "pending_tool": row.pending_tool_name or envelope.get("pending_tool_name"),
            "pending_args": json.loads(row.pending_tool_args_json or "{}"),
            "state_version": envelope.get("version"),
            "message": "Sensitive order tool requires explicit HITL approval to resume.",
            "mode": envelope.get("mode"),
        }


def resume_order_run(
    *,
    run_id: str,
    approve: bool,
    actor: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    Resume a paused agent run after HITL approval of create_mock_purchase_order.

    Requires formal DB approval to still be approved with an unchanged quantity.
    Duplicate resume returns the existing purchase order when already completed.
    """
    init_db()
    _configure_tracing()

    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, run_id)
        if row is None:
            raise AppError(f"No agent run state for {run_id}", code="hitl_missing_run")
        state_json = row.state_json
        recommendation_id = row.recommendation_id
        approval_id = row.approval_id
        row_status = row.status

    envelope = parse_state_envelope(state_json)

    # Duplicate resume: if already completed, return existing PO (no second order).
    if row_status == "completed" and approval_id:
        with get_session() as session:
            existing = purchase_order_repository.get_purchase_order_by_approval(
                session, approval_id
            )
        if existing is not None:
            return {
                "status": "completed",
                "run_id": run_id,
                "purchase_order": existing.model_dump(mode="json"),
                "mode": "idempotent_reload",
                "message": "Purchase order already exists for this approval.",
            }

    if row_status == "rejected":
        return {
            "status": "rejected",
            "run_id": run_id,
            "message": "Sensitive tool approval was previously rejected.",
            "approval_id": approval_id,
        }

    if row_status != "paused":
        return {
            "status": "error",
            "run_id": run_id,
            "error_code": "hitl_not_paused",
            "message": f"Agent run is not paused (status={row_status}).",
            "approval_id": approval_id,
        }

    if not approve:
        reject_approval_id = approval_id or (envelope.get("pending_tool_args") or {}).get(
            "approval_id"
        )
        with get_session() as session:
            audit_repository.save_agent_run_state(
                session,
                run_id=run_id,
                state_json=state_json,
                status="rejected",
                recommendation_id=recommendation_id,
                approval_id=reject_approval_id,
                pending_tool_name=envelope.get("pending_tool_name"),
                pending_tool_args=envelope.get("pending_tool_args") or {},
            )
            audit_repository.write_audit_event(
                session,
                "tool_execution_rejected",
                actor=actor,
                actor_role=actor_role,
                run_id=run_id,
                recommendation_id=recommendation_id,
                approval_id=reject_approval_id,
                details={"approved": False},
            )
        return {
            "status": "rejected",
            "run_id": run_id,
            "approval_id": reject_approval_id,
            "message": "Sensitive tool approval rejected. No purchase order was created.",
        }

    try:
        guard_info = validate_resume_guards(envelope, row_status=row_status)
    except AppError as exc:
        return {
            "status": "error",
            "run_id": run_id,
            "error_code": exc.code,
            "message": exc.message,
            "approval_id": approval_id,
        }

    approval_id = str(guard_info["approval_id"])
    recommendation_id = guard_info.get("recommendation_id") or recommendation_id

    # Deterministic HITL path (no live SDK RunState) — still requires this second approval.
    if envelope.get("mode") == "deterministic_hitl" or not envelope.get("sdk_run_state"):
        return _resume_deterministic_hitl(
            run_id=run_id,
            approval_id=approval_id,
            recommendation_id=str(recommendation_id) if recommendation_id else None,
            actor=actor,
            actor_role=actor_role,
            envelope=envelope,
        )

    return _resume_sdk_hitl(
        run_id=run_id,
        approval_id=approval_id,
        recommendation_id=str(recommendation_id) if recommendation_id else None,
        actor=actor,
        actor_role=actor_role,
        envelope=envelope,
    )


# Backward-compatible alias used by older pages/tests.
resume_order_flow = resume_order_run


def start_order_agent_after_approval(
    *,
    approval_id: str,
    recommendation_id: str,
    actor: str,
    actor_role: str,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    After formal DB approval, start order creation via the sensitive tool.

    Formal approval and SDK/tool HITL approval are both required. Without an
    API key, a deterministic pause envelope is persisted so the UI still asks
    for explicit sensitive-tool confirmation before creating the PO.
    """
    init_db()
    _configure_tracing()

    # Idempotent: existing PO or paused run for this approval.
    pending = get_pending_order_flow(approval_id)
    if pending is not None:
        return pending

    approval = approval_service.get_approval_status(approval_id)
    if approval.get("status") != "approved":
        raise AppError(
            f"Cannot start order flow; approval status is {approval.get('status')}",
            code="approval_not_approved",
        )
    approved_qty = approval.get("approved_final_quantity")
    if approved_qty is None:
        raise AppError(
            "approved_final_quantity is required before order HITL.",
            code="approval_missing_quantity",
        )

    run_id = f"RUN-{uuid4().hex[:12]}"
    idempotency_key = f"hitl-order:{approval_id}"

    # Always pause for sensitive-tool confirmation (with or without API key).
    if not OPENAI_API_KEY:
        envelope = build_pause_envelope(
            approval_id=approval_id,
            recommendation_id=recommendation_id,
            approved_final_quantity=int(approved_qty),
            pending_tool_name="create_mock_purchase_order",
            pending_tool_args={"approval_id": approval_id},
            sdk_run_state=None,
            mode="deterministic_hitl",
            actor=actor,
            actor_role=actor_role,
        )
        _persist_hitl_envelope(
            run_id=run_id,
            envelope=envelope,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            actor=actor,
            actor_role=actor_role,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        return {
            "status": "paused",
            "run_id": run_id,
            "pending_tool": "create_mock_purchase_order",
            "pending_args": {"approval_id": approval_id},
            "state_version": envelope["version"],
            "mode": "deterministic_hitl",
            "message": (
                "Sensitive order tool requires explicit HITL approval to resume. "
                "Formal database approval is already recorded."
            ),
        }

    agent = build_replenishment_agent()
    prompt = (
        f"Formal approval {approval_id} is recorded as approved for "
        f"recommendation {recommendation_id}. "
        "Call get_approval_status, then create_mock_purchase_order "
        f"with approval_id={approval_id} only. "
        "Distinguish agent, human, and approved quantities from tool results. "
        "Do not invent values."
    )
    context = _make_context(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        conversation_id=session_id,
        actor=actor,
        actor_role=actor_role,
        recommendation_id=recommendation_id,
    )
    run_config = _build_run_config(
        workflow_name=WORKFLOW_ORDER,
        group_id=session_id or run_id,
        trace_metadata={
            "run_id": run_id,
            "approval_id": approval_id,
            "recommendation_id": recommendation_id,
            "workflow": WORKFLOW_ORDER,
        },
    )
    try:
        result = _execute_runner(
            agent,
            prompt,
            context=context,
            max_turns=analysis_max_turns(),
            run_config=run_config,
        )
    except Exception as exc:  # noqa: BLE001
        return _map_run_exception(
            exc,
            run_id=run_id,
            store_id="",
            sku="",
            kind="order",
        )

    if result.interruptions:
        state = result.to_state()
        pending_interruption = result.interruptions[0]
        args: dict[str, Any] = {}
        try:
            args = getattr(pending_interruption, "arguments", None) or getattr(
                pending_interruption, "tool_arguments", {}
            ) or {}
            if isinstance(args, str):
                args = json.loads(args)
        except Exception:
            args = {"approval_id": approval_id}
        if not isinstance(args, dict):
            args = {"approval_id": approval_id}
        args.setdefault("approval_id", approval_id)

        sdk_json = state.to_json() if hasattr(state, "to_json") else {"run_id": run_id}
        envelope = build_pause_envelope(
            approval_id=approval_id,
            recommendation_id=recommendation_id,
            approved_final_quantity=int(approved_qty),
            pending_tool_name=getattr(
                pending_interruption, "tool_name", "create_mock_purchase_order"
            ),
            pending_tool_args=args,
            sdk_run_state=sdk_json if isinstance(sdk_json, dict) else {"raw": sdk_json},
            mode="sdk",
            actor=actor,
            actor_role=actor_role,
        )
        _persist_hitl_envelope(
            run_id=run_id,
            envelope=envelope,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            actor=actor,
            actor_role=actor_role,
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        return {
            "status": "paused",
            "run_id": run_id,
            "pending_tool": envelope["pending_tool_name"],
            "pending_args": args,
            "state_version": envelope["version"],
            "mode": "sdk",
            "message": "Sensitive order tool requires explicit HITL approval to resume.",
        }

    # Agent completed without interruption — still verify PO idempotently.
    output = result.final_output
    payload: dict[str, Any]
    if isinstance(output, ReplenishmentAgentDecision):
        payload = output.model_dump(mode="json")
    elif isinstance(output, dict):
        payload = output
    else:
        payload = {"final_output": str(output)}
    with get_session() as session:
        existing = purchase_order_repository.get_purchase_order_by_approval(
            session, approval_id
        )
    if existing is not None:
        payload["purchase_order"] = existing.model_dump(mode="json")
    payload["status"] = "completed"
    payload["run_id"] = run_id
    return payload


def _persist_hitl_envelope(
    *,
    run_id: str,
    envelope: dict[str, Any],
    recommendation_id: str | None,
    approval_id: str,
    actor: str,
    actor_role: str | None,
    user_id: str | None = None,
    session_id: str | None = None,
    idempotency_key: str | None = None,
) -> None:
    with get_session() as session:
        audit_repository.save_agent_run_state(
            session,
            run_id=run_id,
            state_json=envelope_to_json(envelope),
            status="paused",
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            pending_tool_name=envelope.get("pending_tool_name"),
            pending_tool_args=envelope.get("pending_tool_args") or {},
            user_id=user_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )
        audit_repository.write_audit_event(
            session,
            "tool_execution_paused",
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            user_id=user_id,
            session_id=session_id,
            details={
                "pending_tool_name": envelope.get("pending_tool_name"),
                "pending_tool_args": envelope.get("pending_tool_args") or {},
                "state_version": envelope.get("version"),
                "mode": envelope.get("mode"),
            },
        )


def _resume_deterministic_hitl(
    *,
    run_id: str,
    approval_id: str,
    recommendation_id: str | None,
    actor: str,
    actor_role: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    from services import purchase_order_service

    with get_session() as session:
        existing = purchase_order_repository.get_purchase_order_by_approval(
            session, approval_id
        )
    if existing is not None:
        with get_session() as session:
            audit_repository.save_agent_run_state(
                session,
                run_id=run_id,
                state_json=envelope_to_json(envelope),
                status="completed",
                recommendation_id=recommendation_id,
                approval_id=approval_id,
                pending_tool_name=envelope.get("pending_tool_name"),
                pending_tool_args=envelope.get("pending_tool_args") or {},
            )
        return {
            "status": "completed",
            "run_id": run_id,
            "purchase_order": existing.model_dump(mode="json"),
            "mode": "idempotent_reload",
        }

    po = purchase_order_service.create_mock_purchase_order(
        approval_id,
        actor=actor,
        actor_role=actor_role,
        idempotency_key=f"po:{approval_id}",
    )
    with get_session() as session:
        audit_repository.save_agent_run_state(
            session,
            run_id=run_id,
            state_json=envelope_to_json(envelope),
            status="completed",
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            pending_tool_name=envelope.get("pending_tool_name"),
            pending_tool_args=envelope.get("pending_tool_args") or {},
        )
        audit_repository.write_audit_event(
            session,
            "tool_execution_resumed",
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            purchase_order_id=po.purchase_order_id,
            details={"approved": True, "mode": "deterministic_hitl"},
        )
    return {
        "status": "completed",
        "run_id": run_id,
        "purchase_order": po.model_dump(mode="json"),
        "mode": "deterministic_hitl",
        "message": "Purchase order created after sensitive-tool HITL approval.",
    }


def _load_run_state(agent: Any, sdk_payload: dict[str, Any]) -> Any:
    """Load RunState without calling async from_json inside a running loop unsafely."""

    async def _load() -> Any:
        return await RunState.from_json(agent, sdk_payload)

    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if in_loop:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_load())).result()
    return asyncio.run(_load())


def _resume_sdk_hitl(
    *,
    run_id: str,
    approval_id: str,
    recommendation_id: str | None,
    actor: str,
    actor_role: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    agent = build_replenishment_agent()
    sdk_payload = envelope.get("sdk_run_state") or {}
    if not isinstance(sdk_payload, dict):
        return {
            "status": "error",
            "run_id": run_id,
            "error_code": "hitl_state_invalid",
            "message": "Stored SDK run state is invalid.",
        }

    try:
        state = _load_run_state(agent, sdk_payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to reload RunState")
        return {
            "status": "error",
            "run_id": run_id,
            "error_code": "hitl_reload_failed",
            "message": "Could not reload the paused agent run state.",
            "details": type(exc).__name__,
        }

    interruptions = state.get_interruptions()
    if not interruptions:
        # No interruptions left — if PO exists, complete idempotently.
        with get_session() as session:
            existing = purchase_order_repository.get_purchase_order_by_approval(
                session, approval_id
            )
        if existing is not None:
            return {
                "status": "completed",
                "run_id": run_id,
                "purchase_order": existing.model_dump(mode="json"),
                "mode": "idempotent_reload",
            }
        return {
            "status": "error",
            "run_id": run_id,
            "error_code": "hitl_no_interruptions",
            "message": "No interruptions pending on stored run state.",
        }

    for interruption in interruptions:
        state.approve(interruption)

    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "tool_execution_resumed",
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            details={"approved": True, "mode": "sdk"},
        )

    run_config = _build_run_config(
        workflow_name=WORKFLOW_ORDER,
        group_id=run_id,
        trace_metadata={
            "run_id": run_id,
            "recommendation_id": recommendation_id,
            "approval_id": approval_id,
            "workflow": WORKFLOW_ORDER,
            "resume": True,
        },
    )
    try:
        result = _execute_runner(
            agent,
            state,
            max_turns=analysis_max_turns(),
            run_config=run_config,
        )
    except Exception as exc:  # noqa: BLE001
        return _map_run_exception(
            exc,
            run_id=run_id,
            store_id="",
            sku="",
            kind="order",
        )

    if result.interruptions:
        new_state = result.to_state()
        sdk_json = new_state.to_json() if hasattr(new_state, "to_json") else {}
        new_envelope = build_pause_envelope(
            approval_id=approval_id,
            recommendation_id=str(recommendation_id or ""),
            approved_final_quantity=int(
                (envelope.get("guards") or {}).get("approved_final_quantity") or 0
            ),
            pending_tool_name=getattr(
                result.interruptions[0], "tool_name", "create_mock_purchase_order"
            ),
            pending_tool_args={"approval_id": approval_id},
            sdk_run_state=sdk_json if isinstance(sdk_json, dict) else None,
            mode="sdk",
            actor=actor,
            actor_role=actor_role,
        )
        _persist_hitl_envelope(
            run_id=run_id,
            envelope=new_envelope,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            actor=actor,
            actor_role=actor_role,
        )
        return {
            "status": "paused",
            "run_id": run_id,
            "interruptions": [str(i) for i in result.interruptions],
            "message": "Agent paused again for additional tool approval.",
        }

    with get_session() as session:
        existing = purchase_order_repository.get_purchase_order_by_approval(
            session, approval_id
        )
        completed_envelope = dict(envelope)
        completed_envelope["sdk_run_state"] = (
            result.to_state().to_json()
            if hasattr(result, "to_state")
            else envelope.get("sdk_run_state")
        )
        audit_repository.save_agent_run_state(
            session,
            run_id=run_id,
            state_json=envelope_to_json(completed_envelope),
            status="completed",
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            pending_tool_name=envelope.get("pending_tool_name"),
            pending_tool_args=envelope.get("pending_tool_args") or {},
        )

    output = result.final_output
    if isinstance(output, ReplenishmentAgentDecision):
        payload = output.model_dump(mode="json")
    elif isinstance(output, dict):
        payload = output
    else:
        payload = {"final_output": str(output)}
    if existing is not None:
        payload["purchase_order"] = existing.model_dump(mode="json")
    payload["status"] = "completed"
    payload["run_id"] = run_id
    payload["mode"] = "sdk"
    return payload


def _coerce_analysis_output(
    output: Any,
    *,
    run_id: str,
    store_id: str,
    sku: str,
    user_id: str | None,
    session_id: str | None,
    actor: str,
) -> dict[str, Any]:
    if isinstance(output, ReplenishmentAgentDecision):
        data = output.model_dump(mode="json")
        data["run_id"] = run_id
        data["status"] = "completed"
        return data

    if isinstance(output, dict):
        try:
            data = ReplenishmentAgentDecision.model_validate(output).model_dump(mode="json")
            data["run_id"] = run_id
            data["status"] = "completed"
            return data
        except ValidationError:
            return _controlled_analysis_error(
                run_id=run_id,
                store_id=store_id,
                sku=sku,
                error_code="malformed_structured_output",
                message=(
                    "The analysis response was not valid structured output. "
                    "Please retry the recommendation."
                ),
                next_action="blocked",
                risk="manual_review",
            )

    # Unexpected free-text — fall back to deterministic numbers, do not invent.
    try:
        data = _deterministic_analysis(
            store_id,
            sku,
            run_id,
            user_id=user_id,
            session_id=session_id,
            actor=actor,
        )
        data["warnings"] = list(data.get("warnings") or []) + [
            "Model returned unstructured output; used deterministic service values."
        ]
        return data
    except (AppError, ValueError) as exc:
        return _analysis_domain_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            exc=exc,
        )


def _map_run_exception(
    exc: BaseException,
    *,
    run_id: str,
    store_id: str,
    sku: str,
    kind: str,
) -> dict[str, Any]:
    if isinstance(exc, MaxTurnsExceeded):
        logger.exception("Agent exceeded max turns (%s)", kind)
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="max_turns_exceeded",
            message=(
                "The request could not be completed within the allowed number of "
                "steps. Please retry."
            ),
            next_action="blocked",
            risk="manual_review",
        )
    if isinstance(exc, _GUARDRAIL_ERRORS):
        logger.exception("Guardrail tripwire (%s)", kind)
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="guardrail_tripwire",
            message="The request was blocked by a safety check. Please revise and retry.",
            next_action="blocked",
            risk="manual_review",
        )
    if isinstance(exc, (ToolTimeoutError, TimeoutError, asyncio.TimeoutError)):
        logger.exception("Model/tool timeout (%s)", kind)
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="model_timeout",
            message="The model or a tool timed out. Please retry shortly.",
            next_action="blocked",
            risk="manual_review",
        )
    if isinstance(exc, (ModelBehaviorError, ValidationError)):
        logger.exception("Malformed model output (%s)", kind)
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="malformed_structured_output",
            message="The model returned an unexpected response. Please retry.",
            next_action="blocked",
            risk="manual_review",
        )
    if isinstance(exc, AppError):
        logger.exception("Tool/service error (%s)", kind)
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code=exc.code or "tool_error",
            message=exc.message,
            next_action="manual_data_review",
            risk="manual_review",
        )
    if isinstance(exc, ValueError):
        return _analysis_domain_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            exc=exc,
        )

    text = str(exc).lower()
    if "api key" in text or "authentication" in text:
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="missing_api_key",
            message="AI analysis is unavailable due to a configuration issue.",
            next_action="blocked",
            risk="manual_review",
        )
    if "timeout" in text:
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="model_timeout",
            message="The model or a tool timed out. Please retry shortly.",
            next_action="blocked",
            risk="manual_review",
        )

    logger.exception("Unexpected agent run error (%s)", kind)
    return _controlled_analysis_error(
        run_id=run_id,
        store_id=store_id,
        sku=sku,
        error_code="agent_run_failed",
        message="Something went wrong while running the agent. Please try again.",
        next_action="blocked",
        risk="manual_review",
    )


def _controlled_analysis_error(
    *,
    run_id: str,
    store_id: str,
    sku: str,
    error_code: str,
    message: str,
    next_action: str = "blocked",
    risk: str = "manual_review",
) -> dict[str, Any]:
    """Business-safe analysis failure — no invented quantities."""
    return {
        "status": "error",
        "run_id": run_id,
        "store_id": store_id,
        "sku": sku,
        "error_code": error_code,
        "message": message,
        "explanation": message,
        "next_action": next_action,
        "risk": risk,
        "approval_required": True,
        "warnings": [message],
        "tools_used": [],
        "agent_recommended_quantity": None,
        "recommendation_id": None,
    }


def _analysis_domain_error(
    *,
    run_id: str,
    store_id: str,
    sku: str,
    exc: BaseException,
) -> dict[str, Any]:
    text = str(exc)
    lowered = text.lower()
    if "no inventory" in lowered or ("inventory" in lowered and "missing" in lowered):
        return _controlled_analysis_error(
            run_id=run_id,
            store_id=store_id,
            sku=sku,
            error_code="missing_inventory",
            message="Required inventory data is missing for this store and SKU.",
            next_action="manual_data_review",
            risk="insufficient_data",
        )
    return _controlled_analysis_error(
        run_id=run_id,
        store_id=store_id,
        sku=sku,
        error_code="domain_error",
        message=(
            "Required analysis data is unavailable. "
            "Please review the store and SKU selection."
        ),
        next_action="manual_data_review",
        risk="manual_review",
    )


def _verified_facts_from_recommendation(rec: dict[str, Any]) -> list[str]:
    facts = [
        f"recommendation_id={rec.get('recommendation_id')}",
        f"store_id={rec.get('store_id')}",
        f"sku={rec.get('sku')}",
        f"agent_recommended_quantity={rec.get('agent_recommended_quantity')}",
        f"risk_level={rec.get('risk_level')}",
        f"forecast_units={rec.get('forecast_units')}",
    ]
    if rec.get("case_pack") is not None:
        facts.append(f"case_pack={rec.get('case_pack')}")
    if rec.get("in_transit") is not None:
        facts.append(f"in_transit={rec.get('in_transit')}")
    return [f for f in facts if not f.endswith("=None")]


def _infer_follow_up_question_type(question: str) -> FollowUpQuestionType:
    q = (question or "").strip().lower()
    if not q:
        return "general"
    if "missing" in q or "what data" in q or "data quality" in q:
        return "missing_data"
    if "policy" in q or "who can approve" in q or "approval role" in q:
        return "policy_question"
    if any(token in q for token in ("why", "explain", "rationale", "how did", "based on")):
        return "explanation"
    return "general"


def _scenario_result_payload(scenario: dict[str, Any]) -> dict[str, Any]:
    """Keep only JSON-serializable verified scenario values (drop prose lists)."""
    skip = {"verified_facts", "assumptions", "summary"}
    cleaned: dict[str, Any] = {}
    for key, value in scenario.items():
        if key in skip:
            continue
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        cleaned[key] = value
    return cleaned


def _follow_up_policy_block(question: str) -> dict[str, Any] | None:
    """Backward-compatible alias for follow-up prohibition detection."""
    return detect_prohibited_follow_up(question)


def _follow_up_guardrail_prohibition(exc: BaseException) -> dict[str, Any] | None:
    """Map SDK input-guardrail tripwires to a prohibited FollowUpAnswer payload."""
    if not isinstance(exc, InputGuardrailTripwireTriggered):
        return None
    output_info: Any = None
    result = getattr(exc, "guardrail_result", None)
    if result is not None:
        output = getattr(result, "output", None)
        output_info = getattr(output, "output_info", None)
    if isinstance(output_info, dict) and output_info.get("error_code"):
        return {
            "error_code": output_info.get("error_code", "follow_up_prohibited"),
            "message": output_info.get(
                "message",
                "Follow-up chat cannot perform that action. "
                + FOLLOW_UP_PROHIBITED_NEXT_ACTION,
            ),
            "unresolved": list(
                output_info.get("unresolved")
                or [output_info.get("message") or "prohibited follow-up action"]
            ),
            "question_type": "prohibited_action",
            "suggested_next_action": FOLLOW_UP_PROHIBITED_NEXT_ACTION,
            "can_change_business_state": False,
        }
    return {
        "error_code": "follow_up_prohibited",
        "message": (
            "Follow-up chat cannot perform that action. "
            + FOLLOW_UP_PROHIBITED_NEXT_ACTION
        ),
        "unresolved": ["prohibited follow-up action"],
        "question_type": "prohibited_action",
        "suggested_next_action": FOLLOW_UP_PROHIBITED_NEXT_ACTION,
        "can_change_business_state": False,
    }


def _follow_up_prohibited(
    *,
    run_id: str,
    recommendation_id: str,
    policy_block: dict[str, Any],
    conversation_id: str | None = None,
    verified: list[str] | None = None,
) -> dict[str, Any]:
    """Safe prohibited-action response — does not crash the session."""
    return _follow_up_error(
        run_id=run_id,
        recommendation_id=recommendation_id,
        error_code=str(policy_block.get("error_code") or "follow_up_prohibited"),
        message=str(
            policy_block.get("message")
            or "Follow-up chat cannot perform that action."
        ),
        unresolved=list(policy_block.get("unresolved") or []),
        verified=verified,
        question_type="prohibited_action",
        conversation_id=conversation_id,
        suggested_next_action=FOLLOW_UP_PROHIBITED_NEXT_ACTION,
    )


def _extract_quantity_from_question(question: str) -> int | None:
    text = question.lower()
    patterns = (
        r"(?:why not|instead of|order|order(?:ing)?|quantity(?: of)?|qty)\s+(\d+)\s*units?",
        r"\b(\d+)\s*units?\b",
        r"\border\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _extract_delay_days_from_question(question: str) -> int | None:
    text = question.lower()
    if "delay" not in text and "delayed" not in text and "late" not in text:
        return None
    match = re.search(r"(\d+)\s*day", text)
    if match:
        return int(match.group(1))
    word_days = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    word_match = re.search(
        r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten)\s+days?\b",
        text,
    )
    if word_match:
        return word_days[word_match.group(1)]
    return None


def _try_deterministic_scenario_follow_up(
    *,
    run_id: str,
    recommendation: dict[str, Any],
    question: str,
    conversation_id: str | None,
) -> dict[str, Any] | None:
    """Route quantity/delay what-ifs through scenario services (not the model)."""
    rec_id = str(recommendation["recommendation_id"])
    q = question.lower()
    session_key = conversation_id or follow_up_session_id("anonymous", rec_id)

    delay_days = _extract_delay_days_from_question(question)
    if delay_days is not None:
        scenario = scenario_service.evaluate_delay_scenario(rec_id, delay_days)
        answer = FollowUpAnswer(
            recommendation_id=rec_id,
            question_type="delay_scenario",
            answer=f"Hypothetical delay scenario: {scenario['summary']}",
            verified_facts=list(scenario["verified_facts"]),
            assumptions=list(scenario["assumptions"]),
            unresolved_items=[],
            scenario_result=_scenario_result_payload(scenario),
            suggested_next_action="review_recommendation",
            tools_used=["evaluate_delay_scenario"],
            can_change_business_state=False,
        )
        payload = answer.model_dump(mode="json")
        payload["status"] = "completed"
        payload["run_id"] = run_id
        payload["conversation_id"] = session_key
        payload["follow_up_session_id"] = session_key
        payload["mode"] = "scenario_service"
        payload["scenario_type"] = "delay"
        return payload

    proposed = _extract_quantity_from_question(question)
    quantity_intent = bool(
        re.search(
            r"why not order|what if (we |i )?order|"
            r"what happens if (we |i )?order|instead of|\binstead\b|"
            r"already on order|on order|alternate quantity|order only\s+\d+",
            q,
        )
    )
    if proposed is None or not quantity_intent:
        return None

    if "already on order" in q or re.search(r"\bon order\b", q):
        open_qty = int(recommendation.get("in_transit") or 0)
        agent_qty = int(recommendation["agent_recommended_quantity"])
        still_needed = max(agent_qty - proposed, 0)
        open_order_scenario = {
            "status": "ok",
            "scenario_type": "quantity",
            "hypothetical": True,
            "recommendation_id": rec_id,
            "agent_recommended_quantity": agent_qty,
            "assumed_open_order_quantity": proposed,
            "saved_in_transit": open_qty,
            "remaining_need_estimate": still_needed,
        }
        answer = FollowUpAnswer(
            recommendation_id=rec_id,
            question_type="quantity_scenario",
            answer=(
                f"Hypothetical open-order scenario: if {proposed} units are already "
                f"on order (saved in_transit is {open_qty}), the saved recommendation "
                f"is {agent_qty} units. A remaining need of about {still_needed} units "
                "may still apply after accounting for that inbound quantity. "
                "The stored recommendation was not changed."
            ),
            verified_facts=[
                f"recommendation_id={rec_id}",
                f"agent_recommended_quantity={agent_qty}",
                f"assumed_open_order_quantity={proposed}",
                f"saved_in_transit={open_qty}",
                f"remaining_need_estimate={still_needed}",
            ],
            assumptions=[
                "Hypothetical open-order scenario only; the stored recommendation was not changed.",
                "Remaining need estimate subtracts the assumed open-order quantity from the saved recommendation.",
            ],
            unresolved_items=[],
            scenario_result=open_order_scenario,
            suggested_next_action="review_recommendation",
            tools_used=["get_recommendation"],
            can_change_business_state=False,
        )
    else:
        scenario = scenario_service.evaluate_quantity_scenario(rec_id, proposed)
        answer = FollowUpAnswer(
            recommendation_id=rec_id,
            question_type="quantity_scenario",
            answer=f"Hypothetical quantity scenario: {scenario['summary']}",
            verified_facts=list(scenario["verified_facts"]),
            assumptions=list(scenario["assumptions"]),
            unresolved_items=[],
            scenario_result=_scenario_result_payload(scenario),
            suggested_next_action="review_recommendation",
            tools_used=["evaluate_quantity_scenario"],
            can_change_business_state=False,
        )

    payload = answer.model_dump(mode="json")
    payload["status"] = "completed"
    payload["run_id"] = run_id
    payload["conversation_id"] = session_key
    payload["follow_up_session_id"] = session_key
    payload["mode"] = "scenario_service"
    payload["scenario_type"] = "quantity"
    return payload


def _deterministic_follow_up(
    *,
    run_id: str,
    recommendation: dict[str, Any],
    question: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Follow-up without API key — verified facts from the saved recommendation."""
    rec_id = str(recommendation["recommendation_id"])
    facts = _verified_facts_from_recommendation(recommendation)
    qty = recommendation.get("agent_recommended_quantity")
    risk = recommendation.get("risk_level")
    forecast = recommendation.get("forecast_units")
    case_pack = recommendation.get("case_pack")
    rationale = (recommendation.get("rationale") or "").strip()

    q = question.lower()
    question_type = _infer_follow_up_question_type(question)
    if "missing" in q or "what data" in q:
        question_type = "missing_data"
        answer_text = (
            "Based on the saved recommendation, core forecast, inventory, and quantity "
            "fields are present. Review warnings on the Analysis page if any data-quality "
            "flags were raised during generation."
        )
        unresolved: list[str] = []
    elif "risk" in q or "stockout" in q:
        question_type = "explanation"
        answer_text = (
            f"The saved recommendation risk level is {risk}. "
            f"Recommended quantity is {qty} against a forecast of {forecast} units."
        )
        unresolved = []
    elif "reduce" in q:
        question_type = "explanation"
        answer_text = (
            f"The saved recommendation is {qty} units (case pack {case_pack}). "
            "Lowering quantity would reduce cover relative to that recommendation; "
            "ask a specific alternate quantity for a hypothetical scenario."
        )
        unresolved = []
    else:
        answer_text = (
            f"The saved recommendation is {qty} units with risk {risk} and forecast "
            f"{forecast} units"
            + (f" (case pack {case_pack})" if case_pack is not None else "")
            + "."
        )
        if rationale:
            answer_text += f" Saved rationale: {rationale}"
        if not OPENAI_API_KEY:
            answer_text += (
                " AI narrative elaboration is unavailable without an API key; "
                "values above are verified from the saved recommendation."
            )
        unresolved = (
            ["Natural-language elaboration requires OPENAI_API_KEY."]
            if not OPENAI_API_KEY
            else []
        )

    answer = FollowUpAnswer(
        recommendation_id=rec_id,
        question_type=question_type,
        answer=answer_text,
        verified_facts=facts,
        assumptions=[],
        unresolved_items=unresolved,
        scenario_result=None,
        suggested_next_action="review_recommendation",
        tools_used=["get_recommendation"],
        can_change_business_state=False,
    )
    payload = answer.model_dump(mode="json")
    payload["status"] = "completed"
    payload["run_id"] = run_id
    session_key = conversation_id or follow_up_session_id("anonymous", rec_id)
    payload["conversation_id"] = session_key
    payload["follow_up_session_id"] = session_key
    payload["mode"] = "deterministic_fallback"
    return payload


def _follow_up_error(
    *,
    run_id: str,
    recommendation_id: str,
    error_code: str,
    message: str,
    unresolved: list[str] | None = None,
    verified: list[str] | None = None,
    question_type: FollowUpQuestionType = "general",
    conversation_id: str | None = None,
    suggested_next_action: str | None = None,
) -> dict[str, Any]:
    next_action = suggested_next_action
    if next_action is None:
        next_action = (
            FOLLOW_UP_PROHIBITED_NEXT_ACTION
            if question_type == "prohibited_action"
            else "manual_data_review"
        )
    answer = FollowUpAnswer(
        recommendation_id=recommendation_id,
        question_type=question_type,
        answer=message,
        verified_facts=verified or [],
        assumptions=[],
        unresolved_items=unresolved or [message],
        scenario_result=None,
        suggested_next_action=next_action,
        tools_used=[],
        can_change_business_state=False,
    )
    payload = answer.model_dump(mode="json")
    payload["status"] = "error"
    payload["run_id"] = run_id
    payload["error_code"] = error_code
    payload["mode"] = "error"
    if conversation_id:
        payload["conversation_id"] = conversation_id
        payload["follow_up_session_id"] = conversation_id
    return payload


def _deterministic_analysis(
    store_id: str,
    sku: str,
    run_id: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    actor: str = "deterministic_orchestrator",
) -> dict[str, Any]:
    analysis = recommendation_service.build_analysis(store_id, sku)
    product = analysis["product"]
    inventory = analysis["inventory"]
    forecast = analysis["forecast"]
    replenishment = analysis["replenishment"]
    risk = analysis["risk"]

    open_orders = inventory_service.get_open_orders(store_id, sku)
    inventory_stale = inventory_service.is_inventory_stale(inventory)
    rationale = (
        f"{product.product_name} at {store_id} has risk={risk['risk_level']} "
        f"with a {forecast.forecast_units}-unit seven-day forecast. "
        f"Usable on hand {inventory.usable_on_hand} and in transit {inventory.in_transit} "
        f"yield recommended quantity {replenishment.recommended_quantity} "
        f"(case pack {replenishment.case_pack}). Proceed to review."
    )
    recommendation = recommendation_service.create_recommendation_record(
        store_id,
        sku,
        rationale=rationale,
        run_id=run_id,
        actor=actor,
        user_id=user_id,
        session_id=session_id,
    )
    risk_level = str(risk["risk_level"])
    if risk_level not in {
        "stockout",
        "overstock",
        "balanced",
        "manual_review",
        "insufficient_data",
    }:
        risk_level = "manual_review"

    next_action = "review_recommendation"
    warnings: list[str] = []
    if inventory_stale:
        risk_level = "manual_review"
        next_action = "manual_data_review"
        warnings.append(
            "Inventory position appears stale relative to the analysis as-of date."
        )
    elif risk_level == "insufficient_data":
        next_action = "manual_data_review"
        warnings.append("Insufficient sales history for a confident forecast.")
    elif replenishment.recommended_quantity == 0 and risk_level in {
        "balanced",
        "overstock",
    }:
        next_action = "no_order_required"
        warnings.append("Deterministic replenishment recommended zero units.")

    decision = ReplenishmentAgentDecision(
        recommendation_id=recommendation.recommendation_id,
        store_id=store_id,
        sku=sku,
        product_name=product.product_name,
        forecast_days=int(forecast.forecast_days),
        forecast_units=float(forecast.forecast_units),
        average_daily_sales=float(forecast.average_daily_sales),
        usable_on_hand=inventory.usable_on_hand,
        in_transit=inventory.in_transit,
        open_order_quantity=int(open_orders["open_order_quantity"]),
        safety_stock=inventory.safety_stock,
        days_of_supply=(
            float(replenishment.days_of_supply)
            if replenishment.days_of_supply is not None
            else None
        ),
        raw_quantity=float(replenishment.raw_quantity),
        agent_recommended_quantity=replenishment.recommended_quantity,
        case_pack=replenishment.case_pack,
        risk=risk_level,  # type: ignore[arg-type]
        confidence=None,
        confidence_basis=[
            f"forecast_method={forecast.method}",
            f"constraints={','.join(replenishment.constraints_applied) or 'none'}",
        ],
        explanation=rationale,
        approval_required=True,
        next_action=next_action,  # type: ignore[arg-type]
        tools_used=[
            "get_product_details",
            "get_inventory_position",
            "get_open_orders",
            "get_demand_forecast",
            "calculate_replenishment",
            "assess_replenishment_risk",
            "create_recommendation_record",
        ],
        warnings=warnings,
    )
    data = decision.model_dump(mode="json")
    data["run_id"] = run_id
    data["status"] = "completed"
    data["mode"] = "deterministic_fallback"
    data["constraints_applied"] = replenishment.constraints_applied
    return data


def build_order_execution_result(
    *,
    run_id: str,
    approval_id: str,
    status: str,
    agent_recommended_quantity: int,
    human_proposed_quantity: int,
    approved_final_quantity: int | None,
    message: str,
    purchase_order_id: str | None = None,
    next_action: str | None = None,
) -> dict[str, Any]:
    """Helper for order outcomes — structured fields only."""
    allowed = {
        "approval_pending",
        "approved",
        "rejected",
        "order_created",
        "order_failed",
    }
    normalized = status if status in allowed else "order_failed"
    result = OrderExecutionResult(
        run_id=run_id,
        approval_id=approval_id,
        purchase_order_id=purchase_order_id,
        status=normalized,  # type: ignore[arg-type]
        agent_recommended_quantity=agent_recommended_quantity,
        human_proposed_quantity=human_proposed_quantity,
        approved_final_quantity=approved_final_quantity,
        message=message,
        next_action=next_action,
    )
    return result.model_dump(mode="json")


def _persist_run_state(
    run_id: str,
    state: RunState[Any] | Any,
    *,
    recommendation_id: str | None,
    status: str,
    approval_id: str | None = None,
    pending_tool_name: str | None = None,
    pending_tool_args: dict[str, Any] | None = None,
    actor: str = "system",
    actor_role: str | None = None,
) -> None:
    if hasattr(state, "to_json"):
        state_json = json.dumps(state.to_json(), default=str)
    else:
        state_json = json.dumps({"run_id": run_id})
    with get_session() as session:
        audit_repository.save_agent_run_state(
            session,
            run_id=run_id,
            state_json=state_json,
            status=status,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            pending_tool_name=pending_tool_name,
            pending_tool_args=pending_tool_args,
        )
        audit_repository.write_audit_event(
            session,
            "tool_execution_paused",
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            details={
                "pending_tool_name": pending_tool_name,
                "pending_tool_args": pending_tool_args or {},
            },
        )

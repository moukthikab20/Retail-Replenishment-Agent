"""Agent run helpers for Streamlit and HITL resume."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from agents import MaxTurnsExceeded, RunState, Runner, set_tracing_disabled
from agents.tracing import set_tracing_export_api_key

from agent.context import ReplenishmentRunContext
from agent.orchestrator import build_replenishment_agent
from agent.schemas import ReplenishmentAgentDecision
from config import AGENT_MAX_TURNS, OPENAI_API_KEY, TRACE_SENSITIVE_DATA
from database.connection import get_session, init_db
from repositories import audit_repository
from services import recommendation_service

logger = logging.getLogger(__name__)


def _configure_tracing() -> None:
    if not OPENAI_API_KEY:
        set_tracing_disabled(True)
        return
    set_tracing_disabled(False)
    try:
        set_tracing_export_api_key(OPENAI_API_KEY)
    except Exception:
        pass
    # Sensitive data capture remains off unless explicitly enabled
    if not TRACE_SENSITIVE_DATA:
        logger.debug("TRACE_SENSITIVE_DATA disabled")


def run_analysis(store_id: str, sku: str) -> dict[str, Any]:
    """
    Run analysis for store/SKU.

    Uses the OpenAI Agents SDK when OPENAI_API_KEY is set; otherwise runs the
    same deterministic service pipeline and returns a structured decision.
    """
    init_db()
    _configure_tracing()
    run_id = f"RUN-{uuid4().hex[:12]}"

    if not OPENAI_API_KEY:
        return _deterministic_analysis(store_id, sku, run_id)

    agent = build_replenishment_agent()
    prompt = (
        f"Analyze replenishment for store_id={store_id} and sku={sku}. "
        "Use tools for all facts. Save a recommendation. "
        "Do not create a purchase order. Return ReplenishmentAgentDecision "
        "with next_action=await_human_review."
    )
    context = ReplenishmentRunContext(run_id=run_id)
    try:
        result = Runner.run_sync(
            agent,
            prompt,
            context=context,
            max_turns=AGENT_MAX_TURNS,
        )
    except MaxTurnsExceeded as exc:
        logger.exception("Agent exceeded max turns")
        decision = _deterministic_analysis(store_id, sku, run_id)
        decision["explanation"] = (
            decision["explanation"]
            + f" (Agent stopped: max turns exceeded — {exc})"
        )
        decision["tools_used"] = list(dict.fromkeys(decision.get("tools_used", []) + ["max_turns_fallback"]))
        return decision

    if result.interruptions:
        # Analysis tools should not interrupt; if they do, persist state.
        state = result.to_state()
        _persist_run_state(run_id, state, recommendation_id=None, status="paused")
        return {
            "status": "paused",
            "run_id": run_id,
            "interruptions": [str(i) for i in result.interruptions],
            "message": "Agent paused for tool approval unexpectedly during analysis.",
        }

    output = result.final_output
    if isinstance(output, ReplenishmentAgentDecision):
        data = output.model_dump(mode="json")
    elif isinstance(output, dict):
        data = output
    else:
        data = _deterministic_analysis(store_id, sku, run_id)
        data["explanation"] = str(output)
    data["run_id"] = run_id
    data["status"] = "completed"
    return data


def resume_order_flow(
    *,
    run_id: str,
    approve: bool,
    actor: str,
    actor_role: str,
) -> dict[str, Any]:
    """Resume a paused agent run after HITL approval of create_mock_purchase_order."""
    init_db()
    _configure_tracing()
    with get_session() as session:
        row = audit_repository.get_agent_run_state(session, run_id)
        if row is None:
            raise ValueError(f"No paused agent run state for {run_id}")
        state_json = row.state_json
        recommendation_id = row.recommendation_id

    agent = build_replenishment_agent()
    state_payload = json.loads(state_json) if isinstance(state_json, str) else state_json
    state = RunState.from_json(agent, state_payload)

    interruptions = state.get_interruptions()
    if not interruptions:
        raise ValueError("No interruptions pending on stored run state")

    for interruption in interruptions:
        if approve:
            state.approve(interruption)
        else:
            state.reject(interruption)

    with get_session() as session:
        audit_repository.write_audit_event(
            session,
            "tool_execution_resumed" if approve else "tool_execution_paused",
            actor=actor,
            actor_role=actor_role,
            run_id=run_id,
            recommendation_id=recommendation_id,
            details={"approved": approve},
        )

    try:
        result = Runner.run_sync(agent, state, max_turns=AGENT_MAX_TURNS)
    except MaxTurnsExceeded as exc:
        return {"status": "error", "run_id": run_id, "error": f"MaxTurnsExceeded: {exc}"}

    if result.interruptions:
        new_state = result.to_state()
        _persist_run_state(
            run_id,
            new_state,
            recommendation_id=recommendation_id,
            status="paused",
        )
        return {
            "status": "paused",
            "run_id": run_id,
            "interruptions": [str(i) for i in result.interruptions],
        }

    with get_session() as session:
        completed_state = "{}"
        if hasattr(result, "to_state"):
            completed_state = json.dumps(result.to_state().to_json(), default=str)
        audit_repository.save_agent_run_state(
            session,
            run_id=run_id,
            state_json=completed_state,
            status="completed",
            recommendation_id=recommendation_id,
        )

    output = result.final_output
    if isinstance(output, ReplenishmentAgentDecision):
        payload = output.model_dump(mode="json")
    elif isinstance(output, dict):
        payload = output
    else:
        payload = {"final_output": str(output)}
    payload["status"] = "completed"
    payload["run_id"] = run_id
    return payload


def start_order_agent_after_approval(
    *,
    approval_id: str,
    recommendation_id: str,
    actor: str,
    actor_role: str,
) -> dict[str, Any]:
    """
    After formal DB approval, ask the agent to create the mock PO via the
    sensitive tool (may pause for SDK HITL approval).
    """
    init_db()
    _configure_tracing()
    run_id = f"RUN-{uuid4().hex[:12]}"

    if not OPENAI_API_KEY:
        from services import purchase_order_service

        po = purchase_order_service.create_mock_purchase_order(
            approval_id, actor=actor, actor_role=actor_role
        )
        return {
            "status": "completed",
            "run_id": run_id,
            "purchase_order": po.model_dump(mode="json"),
            "mode": "deterministic_fallback",
        }

    agent = build_replenishment_agent()
    prompt = (
        f"Formal approval {approval_id} is recorded as approved for "
        f"recommendation {recommendation_id}. "
        "Call check_approval_status, then create_mock_purchase_order "
        f"with approval_id={approval_id} only. "
        "Distinguish agent, human, and approved quantities from tool results. "
        "Do not invent values."
    )
    try:
        result = Runner.run_sync(agent, prompt, max_turns=AGENT_MAX_TURNS)
    except MaxTurnsExceeded as exc:
        return {"status": "error", "run_id": run_id, "error": str(exc)}

    if result.interruptions:
        state = result.to_state()
        pending = result.interruptions[0]
        args = {}
        try:
            args = getattr(pending, "arguments", None) or getattr(pending, "tool_arguments", {}) or {}
            if isinstance(args, str):
                args = json.loads(args)
        except Exception:
            args = {"approval_id": approval_id}
        _persist_run_state(
            run_id,
            state,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            status="paused",
            pending_tool_name=getattr(pending, "tool_name", "create_mock_purchase_order"),
            pending_tool_args=args if isinstance(args, dict) else {"approval_id": approval_id},
            actor=actor,
            actor_role=actor_role,
        )
        return {
            "status": "paused",
            "run_id": run_id,
            "pending_tool": getattr(pending, "tool_name", "create_mock_purchase_order"),
            "pending_args": args if isinstance(args, dict) else {"approval_id": approval_id},
            "message": "Sensitive order tool requires explicit HITL approval to resume.",
        }

    output = result.final_output
    payload: dict[str, Any]
    if isinstance(output, ReplenishmentAgentDecision):
        payload = output.model_dump(mode="json")
    elif isinstance(output, dict):
        payload = output
    else:
        payload = {"final_output": str(output)}
    payload["status"] = "completed"
    payload["run_id"] = run_id
    return payload


def _deterministic_analysis(store_id: str, sku: str, run_id: str) -> dict[str, Any]:
    analysis = recommendation_service.build_analysis(store_id, sku)
    product = analysis["product"]
    inventory = analysis["inventory"]
    forecast = analysis["forecast"]
    replenishment = analysis["replenishment"]
    risk = analysis["risk"]

    rationale = (
        f"{product.product_name} at {store_id} has risk={risk['risk_level']} "
        f"with a {forecast.forecast_units}-unit seven-day forecast. "
        f"Usable on hand {inventory.usable_on_hand} and in transit {inventory.in_transit} "
        f"yield recommended quantity {replenishment.recommended_quantity} "
        f"(case pack {replenishment.case_pack}). Proceed to human review."
    )
    recommendation = recommendation_service.create_recommendation_record(
        store_id,
        sku,
        rationale=rationale,
        run_id=run_id,
        actor="deterministic_orchestrator",
    )
    decision = ReplenishmentAgentDecision(
        recommendation_id=recommendation.recommendation_id,
        store_id=store_id,
        sku=sku,
        product_name=product.product_name,
        risk=risk["risk_level"],
        forecast_units=float(forecast.forecast_units),
        usable_on_hand=inventory.usable_on_hand,
        in_transit=inventory.in_transit,
        safety_stock=inventory.safety_stock,
        days_of_supply=(
            float(replenishment.days_of_supply)
            if replenishment.days_of_supply is not None
            else None
        ),
        agent_recommended_quantity=replenishment.recommended_quantity,
        approval_required=True,
        required_approval_role="store_manager",
        explanation=rationale,
        next_action="await_human_review",
        tools_used=[
            "get_product_details",
            "get_inventory_position",
            "get_demand_forecast",
            "calculate_replenishment",
            "assess_replenishment_risk",
            "create_recommendation_record",
        ],
    )
    data = decision.model_dump(mode="json")
    data["run_id"] = run_id
    data["status"] = "completed"
    data["mode"] = "deterministic_fallback"
    data["raw_quantity"] = float(replenishment.raw_quantity)
    data["case_pack"] = replenishment.case_pack
    data["average_daily_sales"] = float(forecast.average_daily_sales)
    data["constraints_applied"] = replenishment.constraints_applied
    return data


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

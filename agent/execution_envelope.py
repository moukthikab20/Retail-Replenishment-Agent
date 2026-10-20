"""Versioned agent execution envelope stored in AgentRunStateRow.state_json."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from config import AGENT_RUN_STATE_VERSION

ENVELOPE_SCHEMA_VERSION = max(2, int(AGENT_RUN_STATE_VERSION or 1))

PlanStepStatus = Literal["pending", "running", "completed", "failed", "skipped"]
ToolCallStatus = Literal["started", "completed", "failed", "paused"]


class PlanStep(BaseModel):
    step_id: str
    action: str
    status: PlanStepStatus = "pending"
    tool_name: str | None = None
    result_ref: dict[str, Any] | None = None


class OperationalPlan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)


class ToolExecutionRecord(BaseModel):
    tool_call_id: str
    execution_id: str
    tool_name: str
    status: ToolCallStatus
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    attempt_number: int = 1
    audit_event_id: str | None = None


class ModelTurnRecord(BaseModel):
    """Operational model-turn metadata — never stores chain-of-thought."""

    turn_id: str
    execution_id: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    model_name: str | None = None
    status: str = "started"
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AgentExecutionEnvelope(BaseModel):
    """Operational execution state — never stores chain-of-thought."""

    schema_version: int = ENVELOPE_SCHEMA_VERSION
    goal: str = ""
    plan: OperationalPlan | None = None
    current_step: str | None = None
    next_action: str | None = None
    tool_history: list[ToolExecutionRecord] = Field(default_factory=list)
    model_turns: list[ModelTurnRecord] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    # Legacy HITL fields preserved for order pause/resume compatibility.
    mode: str | None = None  # sdk | deterministic_hitl
    sdk_run_state: dict[str, Any] | None = None
    pending_tool_name: str | None = None
    pending_tool_args: dict[str, Any] = Field(default_factory=dict)
    guards: dict[str, Any] = Field(default_factory=dict)
    version: int | None = None  # envelope schema marker (legacy hitl used this)
    requested_action: str | None = None
    required_role: str | None = None
    waiting_reason: str | None = None


def new_tool_call_id() -> str:
    return f"TC-{uuid4().hex[:12]}"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def envelope_from_legacy(payload: dict[str, Any]) -> AgentExecutionEnvelope:
    """Upgrade HITL pause envelopes and legacy blobs into the typed envelope."""
    if "schema_version" in payload and "goal" in payload:
        return AgentExecutionEnvelope.model_validate(payload)

    # Classic HITL envelope from agent.hitl.build_pause_envelope
    if "guards" in payload and ("mode" in payload or "pending_tool_name" in payload):
        goal = (
            f"Create purchase order for approval "
            f"{(payload.get('guards') or {}).get('approval_id') or 'unknown'}"
        )
        call_id = payload.get("tool_call_id") or (payload.get("guards") or {}).get(
            "tool_call_id"
        )
        return AgentExecutionEnvelope(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            goal=goal,
            plan=OperationalPlan(
                goal=goal,
                steps=[
                    PlanStep(
                        step_id="validate_approval",
                        action="validate_approval",
                        status="completed",
                    ),
                    PlanStep(
                        step_id="create_order",
                        action="create_mock_purchase_order",
                        status="running",
                        tool_name="create_mock_purchase_order",
                    ),
                ],
            ),
            current_step="create_order",
            next_action="await_human_approval",
            mode=payload.get("mode"),
            sdk_run_state=payload.get("sdk_run_state"),
            pending_tool_name=payload.get("pending_tool_name"),
            pending_tool_args=payload.get("pending_tool_args") or {},
            guards=payload.get("guards") or {},
            version=payload.get("version"),
            requested_action=payload.get("pending_tool_name") or "create_mock_purchase_order",
            waiting_reason="Sensitive order tool requires explicit HITL approval.",
            context={
                "legacy_hitl": True,
                "tool_call_id": call_id,
            },
            tool_history=list(payload.get("tool_history") or []),
            model_turns=list(payload.get("model_turns") or []),
        )

    # Bare SDK RunState
    return AgentExecutionEnvelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        goal="Resume paused SDK agent run",
        mode="sdk",
        sdk_run_state=payload if isinstance(payload, dict) else {},
        pending_tool_name="create_mock_purchase_order",
        version=0,
        context={"legacy_sdk_blob": True},
    )


def plan_for_execution_type(
    execution_type: str,
    *,
    goal: str,
    recommendation_id: str | None = None,
) -> OperationalPlan:
    rid = recommendation_id or "unknown"
    if execution_type == "follow_up":
        return OperationalPlan(
            goal=goal,
            steps=[
                PlanStep(
                    step_id="load_recommendation",
                    action="get_recommendation",
                    status="pending",
                    tool_name="get_recommendation",
                ),
                PlanStep(
                    step_id="load_policy",
                    action="get_policy_evaluation",
                    status="pending",
                    tool_name="get_policy_evaluation",
                ),
                PlanStep(step_id="answer", action="answer", status="pending"),
            ],
        )
    if execution_type == "scenario_analysis":
        return OperationalPlan(
            goal=goal,
            steps=[
                PlanStep(
                    step_id="load_recommendation",
                    action="get_recommendation",
                    status="pending",
                    tool_name="get_recommendation",
                ),
                PlanStep(
                    step_id="evaluate_scenario",
                    action="evaluate_quantity_or_delay_scenario",
                    status="pending",
                ),
                PlanStep(
                    step_id="explain_hypothetical",
                    action="explain_hypothetical_result",
                    status="pending",
                ),
            ],
        )
    if execution_type == "order_execution":
        return OperationalPlan(
            goal=goal,
            steps=[
                PlanStep(
                    step_id="validate_approval",
                    action="validate_approval",
                    status="pending",
                ),
                PlanStep(
                    step_id="prepare_order_tool",
                    action="prepare_order_tool",
                    status="pending",
                    tool_name="create_mock_purchase_order",
                ),
                PlanStep(
                    step_id="await_hitl",
                    action="wait_for_human",
                    status="pending",
                ),
                PlanStep(
                    step_id="create_order",
                    action="create_mock_purchase_order",
                    status="pending",
                    tool_name="create_mock_purchase_order",
                ),
                PlanStep(step_id="complete", action="complete", status="pending"),
            ],
        )
    # recommendation_analysis default
    return OperationalPlan(
        goal=goal or f"Analyze recommendation {rid}",
        steps=[
            PlanStep(
                step_id="gather_inputs",
                action="gather_analysis_inputs",
                status="pending",
            ),
            PlanStep(
                step_id="create_recommendation",
                action="create_recommendation_record",
                status="pending",
                tool_name="create_recommendation_record",
            ),
            PlanStep(step_id="complete", action="complete", status="pending"),
        ],
    )

"""Deterministic plan templates by workflow — no LLM prompt construction."""

from __future__ import annotations

from datetime import datetime, timezone

from planner.contracts import ExecutionContext, ExecutionPolicy, Plan, PlanStep, RetryPolicy
from planner.types import FailureAction, PlanStepType


def _step(
    step_id: str,
    step_type: PlanStepType,
    *,
    name: str = "",
    deps: list[str] | None = None,
    tool: str | None = None,
    parallel_group: str | None = None,
    expected_output: str | None = None,
    retries: int = 1,
    on_failure: FailureAction = FailureAction.FAIL,
    timeout: float = 30.0,
    metadata: dict | None = None,
) -> PlanStep:
    return PlanStep(
        id=step_id,
        type=step_type,
        name=name or step_id,
        dependencies=list(deps or []),
        tool=tool,
        parallel_group=parallel_group,
        expected_output=expected_output,
        timeout_seconds=timeout,
        retry_policy=RetryPolicy(max_attempts=retries, on_failure=on_failure),
        metadata=dict(metadata or {}),
    )


def build_template_plan(
    context: ExecutionContext,
    *,
    policy: ExecutionPolicy,
    provider_name: str = "mock",
) -> Plan:
    workflow = (context.workflow or "recommendation_analysis").strip().lower()
    goal = context.goal or context.objective or f"Execute {workflow}"
    now = datetime.now(timezone.utc)

    if workflow in {"follow_up", "follow-up"}:
        steps = [
            _step(
                "load_memory",
                PlanStepType.ACTION,
                name="Load memory context",
                expected_output="memory_context",
            ),
            _step(
                "load_recommendation",
                PlanStepType.TOOL,
                name="Load recommendation",
                deps=["load_memory"],
                tool="get_recommendation",
                parallel_group="gather",
            ),
            _step(
                "load_policy",
                PlanStepType.TOOL,
                name="Load policy",
                deps=["load_memory"],
                tool="get_policy_evaluation",
                parallel_group="gather",
            ),
            _step(
                "evaluate_decision",
                PlanStepType.DECISION,
                name="Evaluate decision candidates",
                deps=["load_recommendation", "load_policy"],
                expected_output="decision_outcome",
            ),
            _step(
                "llm_answer",
                PlanStepType.LLM,
                name="Compose follow-up answer",
                deps=["evaluate_decision"],
                expected_output="follow_up_answer",
            ),
            _step("finish", PlanStepType.FINISH, name="Finish", deps=["llm_answer"]),
        ]
    elif workflow in {"order_execution", "order"}:
        steps = [
            _step(
                "validate_approval",
                PlanStepType.DECISION,
                name="Validate approval",
                expected_output="approval_valid",
            ),
            _step(
                "prepare_order",
                PlanStepType.TOOL,
                name="Prepare order tool",
                deps=["validate_approval"],
                tool="get_approval_status",
            ),
            _step(
                "await_hitl",
                PlanStepType.APPROVAL,
                name="Wait for human approval",
                deps=["prepare_order"],
                expected_output="human_decision",
                on_failure=FailureAction.MANUAL,
            ),
            _step(
                "create_order",
                PlanStepType.TOOL,
                name="Create purchase order",
                deps=["await_hitl"],
                tool="create_mock_purchase_order",
                retries=1,
            ),
            _step("finish", PlanStepType.FINISH, name="Finish", deps=["create_order"]),
        ]
    elif workflow in {"scenario_analysis", "scenario"}:
        steps = [
            _step(
                "load_recommendation",
                PlanStepType.TOOL,
                name="Load recommendation",
                tool="get_recommendation",
            ),
            _step(
                "evaluate_scenario",
                PlanStepType.DECISION,
                name="evaluate_quantity_or_delay_scenario",
                deps=["load_recommendation"],
                expected_output="scenario_selected",
            ),
            _step(
                "evaluate_quantity",
                PlanStepType.TOOL,
                name="Quantity scenario",
                deps=["evaluate_scenario"],
                tool="evaluate_quantity_scenario",
                parallel_group="scenarios",
            ),
            _step(
                "evaluate_delay",
                PlanStepType.TOOL,
                name="Delay scenario",
                deps=["evaluate_scenario"],
                tool="evaluate_delay_scenario",
                parallel_group="scenarios",
            ),
            _step(
                "explain_hypothetical",
                PlanStepType.LLM,
                name="explain_hypothetical_result",
                deps=["evaluate_quantity", "evaluate_delay"],
            ),
            _step("finish", PlanStepType.FINISH, name="complete", deps=["explain_hypothetical"]),
        ]
    else:
        # recommendation_analysis / generic — fan-out gather then fan-in to recommendation
        steps = [
            _step(
                "load_memory",
                PlanStepType.ACTION,
                name="Load memory context",
                expected_output="memory_context",
            ),
            _step(
                "get_product",
                PlanStepType.TOOL,
                name="Product details",
                deps=["load_memory"],
                tool="get_product_details",
                parallel_group="inputs",
                retries=2,
                on_failure=FailureAction.RETRY,
            ),
            _step(
                "get_inventory",
                PlanStepType.TOOL,
                name="Inventory position",
                deps=["load_memory"],
                tool="get_inventory_position",
                parallel_group="inputs",
                retries=2,
            ),
            _step(
                "get_forecast",
                PlanStepType.TOOL,
                name="Demand forecast",
                deps=["load_memory"],
                tool="get_demand_forecast",
                parallel_group="inputs",
            ),
            _step(
                "evaluate_decision",
                PlanStepType.DECISION,
                name="Evaluate decision candidates",
                deps=["get_product", "get_inventory", "get_forecast"],
                expected_output="decision_outcome",
            ),
            _step(
                "llm_orchestrate",
                PlanStepType.LLM,
                name="LLM orchestration turn",
                deps=["evaluate_decision"],
                expected_output="orchestration_summary",
            ),
            _step(
                "create_recommendation",
                PlanStepType.TOOL,
                name="Create recommendation record",
                deps=["llm_orchestrate"],
                tool="create_recommendation_record",
                metadata={"delegated": True},
            ),
            _step(
                "finish",
                PlanStepType.FINISH,
                name="Finish",
                deps=["create_recommendation"],
            ),
        ]

    # Cap depth
    if len(steps) > policy.max_depth:
        steps = steps[: max(1, policy.max_depth - 1)]
        steps.append(
            _step("finish", PlanStepType.FINISH, name="Finish", deps=[steps[-1].id])
        )

    return Plan(
        goal=goal,
        objective=context.goal or goal,
        workflow=workflow,
        steps=steps,
        provider=provider_name,
        max_depth=policy.max_depth,
        created_at=now,
        updated_at=now,
        metadata={
            "execution_id": context.execution_id,
            "store_id": context.store_id,
            "sku": context.sku,
            "recommendation_id": context.recommendation_id,
            "approval_id": context.approval_id,
        },
    )

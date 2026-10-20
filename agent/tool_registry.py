"""Control metadata for agent tools — wraps existing @function_tool implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ToolCategory(StrEnum):
    ANALYSIS = "analysis"
    FOLLOW_UP = "follow_up"
    SCENARIO = "scenario"
    WORKFLOW = "workflow"
    ORDER = "order"
    DATA = "data"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    category: ToolCategory
    read_only: bool
    requires_authorization: bool = False
    required_permission: str | None = None
    idempotent: bool = True
    retryable: bool = True
    max_attempts: int = 3
    timeout_seconds: int = 30
    audit_event_name: str = "agent_tool_completed"
    description: str = ""


# Metadata only — implementations remain in agent.tools
TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "get_product_details": ToolDefinition(
        name="get_product_details",
        category=ToolCategory.DATA,
        read_only=True,
        description="Product master attributes",
    ),
    "get_inventory_position": ToolDefinition(
        name="get_inventory_position",
        category=ToolCategory.DATA,
        read_only=True,
        description="On-hand / in-transit inventory",
    ),
    "get_open_orders": ToolDefinition(
        name="get_open_orders",
        category=ToolCategory.DATA,
        read_only=True,
    ),
    "get_demand_forecast": ToolDefinition(
        name="get_demand_forecast",
        category=ToolCategory.DATA,
        read_only=True,
    ),
    "get_forecast": ToolDefinition(
        name="get_forecast",
        category=ToolCategory.DATA,
        read_only=True,
    ),
    "calculate_replenishment": ToolDefinition(
        name="calculate_replenishment",
        category=ToolCategory.ANALYSIS,
        read_only=True,
        description="Deterministic replenishment math",
    ),
    "assess_replenishment_risk": ToolDefinition(
        name="assess_replenishment_risk",
        category=ToolCategory.ANALYSIS,
        read_only=True,
    ),
    "create_recommendation_record": ToolDefinition(
        name="create_recommendation_record",
        category=ToolCategory.WORKFLOW,
        read_only=False,
        requires_authorization=True,
        required_permission="create_recommendation",
        idempotent=True,
        retryable=False,
        audit_event_name="agent_tool_completed",
    ),
    "get_recommendation": ToolDefinition(
        name="get_recommendation",
        category=ToolCategory.DATA,
        read_only=True,
        description="Load persisted recommendation by ID",
    ),
    "get_recommendation_history": ToolDefinition(
        name="get_recommendation_history",
        category=ToolCategory.DATA,
        read_only=True,
    ),
    "get_policy_evaluation": ToolDefinition(
        name="get_policy_evaluation",
        category=ToolCategory.DATA,
        read_only=True,
    ),
    "get_order_terms": ToolDefinition(
        name="get_order_terms",
        category=ToolCategory.DATA,
        read_only=True,
    ),
    "get_human_review_status": ToolDefinition(
        name="get_human_review_status",
        category=ToolCategory.WORKFLOW,
        read_only=True,
    ),
    "get_approval_status": ToolDefinition(
        name="get_approval_status",
        category=ToolCategory.WORKFLOW,
        read_only=True,
    ),
    "create_approval_request": ToolDefinition(
        name="create_approval_request",
        category=ToolCategory.WORKFLOW,
        read_only=False,
        requires_authorization=True,
        required_permission="create_approval",
        idempotent=True,
        retryable=False,
    ),
    "create_mock_purchase_order": ToolDefinition(
        name="create_mock_purchase_order",
        category=ToolCategory.ORDER,
        read_only=False,
        requires_authorization=True,
        required_permission="create_purchase_order",
        idempotent=True,
        retryable=False,
        max_attempts=1,
        audit_event_name="agent_tool_completed",
        description="Sensitive order tool — HITL required",
    ),
    "get_purchase_order_status": ToolDefinition(
        name="get_purchase_order_status",
        category=ToolCategory.ORDER,
        read_only=True,
    ),
    "evaluate_quantity_scenario": ToolDefinition(
        name="evaluate_quantity_scenario",
        category=ToolCategory.SCENARIO,
        read_only=True,
        description="Hypothetical quantity what-if — never mutates recommendation",
    ),
    "evaluate_delay_scenario": ToolDefinition(
        name="evaluate_delay_scenario",
        category=ToolCategory.SCENARIO,
        read_only=True,
        description="Hypothetical delay what-if",
    ),
}


def get_tool_definition(name: str) -> ToolDefinition | None:
    return TOOL_REGISTRY.get(name)


def list_tool_definitions(*, category: str | None = None) -> list[ToolDefinition]:
    tools = list(TOOL_REGISTRY.values())
    if category:
        tools = [t for t in tools if t.category == category]
    return tools


def tool_allows_retry(name: str) -> bool:
    meta = get_tool_definition(name)
    if meta is None:
        return False
    return bool(meta.retryable and meta.idempotent)


def tool_is_read_only(name: str) -> bool:
    meta = get_tool_definition(name)
    return True if meta is None else meta.read_only


def assert_tool_authorized(
    name: str,
    *,
    actor_role: str | None,
    surface: str | None = None,
) -> None:
    """Lightweight registry gate — service-layer auth remains authoritative."""
    from services.errors import AppError
    from services import auth_service

    meta = get_tool_definition(name)
    if meta is None:
        raise AppError(f"Unknown tool: {name}", code="invalid_tool_arguments")
    if not meta.requires_authorization:
        return
    if meta.name == "create_mock_purchase_order":
        if actor_role and not auth_service.can_create_purchase_order(actor_role):
            raise AppError(
                "Not authorized to create purchase orders.",
                code="authorization_denied",
            )
        return
    if meta.name == "create_approval_request":
        if actor_role and not auth_service.can_approve(actor_role):
            # create_approval may still be allowed for submitters in some roles
            pass
        return


def registry_contract_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "category": str(t.category),
            "read_only": t.read_only,
            "requires_authorization": t.requires_authorization,
            "idempotent": t.idempotent,
            "retryable": t.retryable,
            "max_attempts": t.max_attempts,
        }
        for t in TOOL_REGISTRY.values()
    ]


# Tools permitted per durable execution type (surface control; SDK lists still apply).
_EXECUTION_TYPE_TOOLS: dict[str, frozenset[str]] = {
    "recommendation_analysis": frozenset(
        {
            "get_product_details",
            "get_inventory_position",
            "get_open_orders",
            "get_demand_forecast",
            "get_forecast",
            "calculate_replenishment",
            "assess_replenishment_risk",
            "create_recommendation_record",
            "get_recommendation",
            "get_recommendation_history",
            "get_policy_evaluation",
            "get_order_terms",
        }
    ),
    "follow_up": frozenset(
        {
            "get_product_details",
            "get_inventory_position",
            "get_open_orders",
            "get_demand_forecast",
            "get_forecast",
            "calculate_replenishment",
            "assess_replenishment_risk",
            "get_recommendation",
            "get_recommendation_history",
            "get_policy_evaluation",
            "get_order_terms",
            "get_human_review_status",
            "get_approval_status",
            "get_purchase_order_status",
            "evaluate_quantity_scenario",
            "evaluate_delay_scenario",
        }
    ),
    "scenario_analysis": frozenset(
        {
            "get_recommendation",
            "get_policy_evaluation",
            "get_inventory_position",
            "evaluate_quantity_scenario",
            "evaluate_delay_scenario",
            "get_order_terms",
        }
    ),
    "order_execution": frozenset(
        {
            "get_recommendation",
            "get_human_review_status",
            "get_approval_status",
            "create_approval_request",
            "create_mock_purchase_order",
            "get_purchase_order_status",
            "get_order_terms",
        }
    ),
}


def get_allowed_tools_for_execution_type(execution_type: str | None) -> frozenset[str] | None:
    """Return allowed tool names, or None if execution_type is unrestricted/unknown."""
    if not execution_type:
        return None
    return _EXECUTION_TYPE_TOOLS.get(str(execution_type))


def assert_tool_allowed_for_execution(
    tool_name: str,
    *,
    execution_type: str | None,
    actor_role: str | None = None,
) -> ToolDefinition:
    """Registry gate: registered + permitted for execution type + auth metadata."""
    from services.errors import AppError

    meta = get_tool_definition(tool_name)
    if meta is None:
        raise AppError(f"Unknown/unregistered tool: {tool_name}", code="invalid_tool_arguments")
    allowed = get_allowed_tools_for_execution_type(execution_type)
    if allowed is not None and tool_name not in allowed:
        raise AppError(
            f"Tool {tool_name} is not permitted for execution_type={execution_type}",
            code="policy_prohibited",
        )
    assert_tool_authorized(tool_name, actor_role=actor_role)
    return meta

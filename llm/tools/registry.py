"""Orchestration-layer tool registry — LLM may invoke only registered tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from llm.types import ToolDomain


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    domain: ToolDomain
    description: str = ""
    read_only: bool = True


# Server-side registry. Execution remains in agent/services — this gates names only.
ORCHESTRATION_TOOL_REGISTRY: dict[str, RegisteredTool] = {
    # Inventory
    "get_inventory_position": RegisteredTool(
        "get_inventory_position", ToolDomain.INVENTORY, "Current inventory", True
    ),
    "get_open_orders": RegisteredTool(
        "get_open_orders", ToolDomain.INVENTORY, "Open inbound orders", True
    ),
    "get_demand_forecast": RegisteredTool(
        "get_demand_forecast", ToolDomain.INVENTORY, "Demand forecast", True
    ),
    "get_forecast": RegisteredTool(
        "get_forecast", ToolDomain.INVENTORY, "Demand forecast alias", True
    ),
    # Recommendation
    "calculate_replenishment": RegisteredTool(
        "calculate_replenishment", ToolDomain.RECOMMENDATION, "Deterministic math", True
    ),
    "assess_replenishment_risk": RegisteredTool(
        "assess_replenishment_risk", ToolDomain.RECOMMENDATION, "Risk assessment", True
    ),
    "create_recommendation_record": RegisteredTool(
        "create_recommendation_record",
        ToolDomain.RECOMMENDATION,
        "Persist recommendation",
        False,
    ),
    "get_recommendation": RegisteredTool(
        "get_recommendation", ToolDomain.RECOMMENDATION, "Load recommendation", True
    ),
    "get_recommendation_history": RegisteredTool(
        "get_recommendation_history", ToolDomain.RECOMMENDATION, "History", True
    ),
    "get_product_details": RegisteredTool(
        "get_product_details", ToolDomain.RECOMMENDATION, "Product master", True
    ),
    "evaluate_quantity_scenario": RegisteredTool(
        "evaluate_quantity_scenario", ToolDomain.RECOMMENDATION, "Quantity what-if", True
    ),
    "evaluate_delay_scenario": RegisteredTool(
        "evaluate_delay_scenario", ToolDomain.RECOMMENDATION, "Delay what-if", True
    ),
    # Supplier
    "get_order_terms": RegisteredTool(
        "get_order_terms", ToolDomain.SUPPLIER, "Supplier / order terms", True
    ),
    # Policy
    "get_policy_evaluation": RegisteredTool(
        "get_policy_evaluation", ToolDomain.POLICY, "Policy evaluation", True
    ),
    # ERP
    "create_mock_purchase_order": RegisteredTool(
        "create_mock_purchase_order", ToolDomain.ERP, "Create PO", False
    ),
    "get_purchase_order_status": RegisteredTool(
        "get_purchase_order_status", ToolDomain.ERP, "PO status", True
    ),
    # Knowledge
    "retrieve_related_memory": RegisteredTool(
        "retrieve_related_memory", ToolDomain.KNOWLEDGE, "Knowledge retrieval", True
    ),
    # Approval
    "get_human_review_status": RegisteredTool(
        "get_human_review_status", ToolDomain.APPROVAL, "Human review status", True
    ),
    "get_approval_status": RegisteredTool(
        "get_approval_status", ToolDomain.APPROVAL, "Approval status", True
    ),
    "create_approval_request": RegisteredTool(
        "create_approval_request", ToolDomain.APPROVAL, "Create approval", False
    ),
    # Agent Operations
    "get_agent_execution_detail": RegisteredTool(
        "get_agent_execution_detail",
        ToolDomain.AGENT_OPERATIONS,
        "Execution detail",
        True,
    ),
    "list_agent_executions": RegisteredTool(
        "list_agent_executions", ToolDomain.AGENT_OPERATIONS, "List executions", True
    ),
}


class ToolRegistry:
    """Allow-list registry for LLM tool names."""

    def __init__(self, tools: dict[str, RegisteredTool] | None = None) -> None:
        self._tools = dict(tools or ORCHESTRATION_TOOL_REGISTRY)

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def list_tools(self, *, domain: ToolDomain | None = None) -> list[RegisteredTool]:
        tools = list(self._tools.values())
        if domain is not None:
            tools = [t for t in tools if t.domain == domain]
        return tools

    def list_names(self, *, domain: ToolDomain | None = None) -> list[str]:
        return [t.name for t in self.list_tools(domain=domain)]

    def assert_registered(self, name: str) -> RegisteredTool:
        tool = self.get(name)
        if tool is None:
            raise ValueError(f"Hallucinated or unregistered tool: {name}")
        return tool

    def filter_allowed(self, names: list[str]) -> list[str]:
        return [n for n in names if self.is_registered(n)]


# Optional local executors for knowledge/ops tools (server-side only).
def execute_registered_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    registry: ToolRegistry | None = None,
) -> dict[str, Any]:
    """
    Execute a narrow set of orchestration tools server-side.
    Most tools remain in agent.tools — this validates registration first.
    """
    reg = registry or ToolRegistry()
    reg.assert_registered(name)
    args = dict(arguments or {})
    if name == "retrieve_related_memory":
        from memory.service import retrieve_related_memory

        result = retrieve_related_memory(
            recommendation_id=args.get("recommendation_id"),
            approval_id=args.get("approval_id"),
            store_id=args.get("store_id"),
            sku=args.get("sku"),
            supplier_id=args.get("supplier_id"),
            purchase_order_id=args.get("purchase_order_id"),
            execution_id=args.get("execution_id"),
            limit=args.get("limit"),
        )
        return {
            "source": result.source,
            "record_count": len(result.records),
            "records": [r.model_dump(mode="json") for r in result.records[:20]],
        }
    if name == "get_agent_execution_detail":
        from services import agent_ops_service

        detail = agent_ops_service.get_agent_execution_detail(str(args.get("execution_id") or ""))
        return detail or {"found": False}
    if name == "list_agent_executions":
        from services import agent_ops_service

        return {
            "items": agent_ops_service.list_agent_executions(
                limit=int(args.get("limit") or 20)
            )
        }
    return {
        "status": "delegated",
        "tool": name,
        "message": "Tool is registered; execution remains in Agent Runtime / services.",
        "arguments": args,
    }

"""Decision Intelligence enums and constants."""

from __future__ import annotations

from enum import StrEnum


class DecisionAction(StrEnum):
    CREATE_PURCHASE_ORDER = "create_purchase_order"
    TRANSFER_INVENTORY = "transfer_inventory"
    DELAY_PURCHASE = "delay_purchase"
    SPLIT_ORDER = "split_order"
    ESCALATE_APPROVAL = "escalate_approval"
    CHANGE_SUPPLIER = "change_supplier"
    WAIT_FOR_HUMAN = "wait_for_human"
    REJECT_RECOMMENDATION = "reject_recommendation"
    NO_ACTION = "no_action"


class DecisionStrategyName(StrEnum):
    LOWEST_RISK = "lowest_risk"
    LOWEST_COST = "lowest_cost"
    FASTEST_DELIVERY = "fastest_delivery"
    BALANCED = "balanced"
    BUSINESS_POLICY_FIRST = "business_policy_first"
    MOCK = "mock"


class ScoreDimension(StrEnum):
    POLICY_COMPLIANCE = "policy_compliance"
    INVENTORY_RISK = "inventory_risk"
    SUPPLIER_RELIABILITY = "supplier_reliability"
    COST = "cost"
    LEAD_TIME = "lead_time"
    FORECAST_CONFIDENCE = "forecast_confidence"
    OPERATIONAL_COMPLEXITY = "operational_complexity"
    HISTORICAL_SUCCESS = "historical_success"
    ERP_RISK = "erp_risk"
    HUMAN_APPROVAL_IMPACT = "human_approval_impact"


class RiskCategory(StrEnum):
    INVENTORY = "inventory"
    FINANCIAL = "financial"
    SUPPLIER = "supplier"
    ERP = "erp"
    OPERATIONAL = "operational"
    COMPLIANCE = "compliance"
    HUMAN = "human"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionStatus(StrEnum):
    EVALUATED = "evaluated"
    SELECTED = "selected"
    ESCALATED = "escalated"
    FAILED = "failed"
    DEGRADED = "degraded"


ACTION_LABELS: dict[str, str] = {
    DecisionAction.CREATE_PURCHASE_ORDER: "Create Purchase Order",
    DecisionAction.TRANSFER_INVENTORY: "Transfer Inventory",
    DecisionAction.DELAY_PURCHASE: "Delay Purchase",
    DecisionAction.SPLIT_ORDER: "Split Order",
    DecisionAction.ESCALATE_APPROVAL: "Escalate Approval",
    DecisionAction.CHANGE_SUPPLIER: "Change Supplier",
    DecisionAction.WAIT_FOR_HUMAN: "Wait For Human",
    DecisionAction.REJECT_RECOMMENDATION: "Reject Recommendation",
    DecisionAction.NO_ACTION: "No Action",
}

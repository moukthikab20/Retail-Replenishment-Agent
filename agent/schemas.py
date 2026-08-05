"""Typed schemas for agent tools and structured output."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StoreSkuInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: str
    sku: str


class RecommendationIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str


class ApprovalIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str


class PurchaseOrderIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_id: str


class CreateApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str


class ForecastToolResult(BaseModel):
    """Verified forecast payload passed into create_recommendation_record."""

    model_config = ConfigDict(extra="forbid")

    forecast_units: float
    average_daily_sales: float = 0.0
    forecast_days: int = 7
    method: str | None = None
    store_id: str | None = None
    sku: str | None = None


class ReplenishmentToolResult(BaseModel):
    """Verified replenishment payload passed into create_recommendation_record."""

    model_config = ConfigDict(extra="forbid")

    recommended_quantity: int
    raw_quantity: float = 0.0
    case_pack: int = 1
    days_of_supply: float | None = None
    constraints_applied: list[str] = Field(default_factory=list)
    usable_on_hand: int | None = None
    in_transit: int | None = None
    safety_stock: int | None = None
    forecast_units: float | None = None


class RiskToolResult(BaseModel):
    """Verified risk payload passed into create_recommendation_record."""

    model_config = ConfigDict(extra="forbid")

    risk_level: str
    reasons: list[str] = Field(default_factory=list)
    projected_days_of_supply: float | None = None


RiskLevel = Literal[
    "stockout",
    "overstock",
    "balanced",
    "manual_review",
    "insufficient_data",
]

AnalysisNextAction = Literal[
    "review_recommendation",
    "no_order_required",
    "manual_data_review",
    "blocked",
]

OrderStatus = Literal[
    "approval_pending",
    "approved",
    "rejected",
    "order_created",
    "order_failed",
]

FollowUpQuestionType = Literal[
    "explanation",
    "quantity_scenario",
    "delay_scenario",
    "missing_data",
    "policy_question",
    "prohibited_action",
    "general",
]


class ReplenishmentAgentDecision(BaseModel):
    """Structured analysis output — UI must read these fields, not prose."""

    model_config = ConfigDict(extra="ignore")

    recommendation_id: str
    store_id: str
    sku: str
    product_name: str
    forecast_days: int = 7
    forecast_units: float
    average_daily_sales: float = 0.0
    usable_on_hand: int
    in_transit: int
    open_order_quantity: int = 0
    safety_stock: int
    days_of_supply: float | None = None
    raw_quantity: float = 0.0
    agent_recommended_quantity: int
    case_pack: int = 1
    risk: RiskLevel
    confidence: float | None = None
    confidence_basis: list[str] = Field(default_factory=list)
    explanation: str
    approval_required: bool = True
    next_action: AnalysisNextAction = "review_recommendation"
    tools_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FollowUpAnswer(BaseModel):
    """Structured follow-up answer grounded in stored/tool-verified facts."""

    model_config = ConfigDict(extra="ignore")

    recommendation_id: str
    question_type: FollowUpQuestionType = "general"
    answer: str
    verified_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    scenario_result: dict[str, Any] | None = None
    suggested_next_action: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    can_change_business_state: bool = False

    @field_validator("can_change_business_state", mode="before")
    @classmethod
    def _follow_up_never_mutates(cls, _value: Any) -> bool:
        """Follow-up answers are explanatory/hypothetical only."""
        return False

    @field_validator("scenario_result")
    @classmethod
    def _scenario_result_json_safe(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("scenario_result must contain only JSON-serializable values") from exc
        return value


class OrderExecutionResult(BaseModel):
    """Structured outcome for approval/order execution runs."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    approval_id: str
    purchase_order_id: str | None = None
    status: OrderStatus
    agent_recommended_quantity: int
    human_proposed_quantity: int
    approved_final_quantity: int | None = None
    message: str
    next_action: str | None = None

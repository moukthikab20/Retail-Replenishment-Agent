"""Typed schemas for agent tools and structured output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StoreSkuInput(BaseModel):
    store_id: str
    sku: str


class RecommendationIdInput(BaseModel):
    recommendation_id: str


class ApprovalIdInput(BaseModel):
    approval_id: str


class PurchaseOrderIdInput(BaseModel):
    purchase_order_id: str


class CreateRecommendationInput(BaseModel):
    store_id: str
    sku: str
    rationale: str = Field(
        description="Explanation using only tool-derived facts; do not invent quantities."
    )


class CreateApprovalInput(BaseModel):
    review_id: str


class ReplenishmentAgentDecision(BaseModel):
    recommendation_id: str
    store_id: str
    sku: str
    product_name: str
    risk: str
    forecast_units: float
    usable_on_hand: int
    in_transit: int
    safety_stock: int
    days_of_supply: float | None
    agent_recommended_quantity: int
    approval_required: bool = True
    required_approval_role: str = "store_manager"
    explanation: str
    next_action: Literal[
        "await_human_review",
        "await_approval",
        "create_order",
        "completed",
        "rejected",
    ] = "await_human_review"
    tools_used: list[str] = Field(default_factory=list)

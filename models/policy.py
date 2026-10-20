"""Policy configuration and evaluation domain models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Disposition = Literal["auto_release", "human_review", "blocked", "no_order"]
RuleResult = Literal["pass", "fail", "skip"]
RuleAction = Literal["auto_release", "human_review", "blocked", "no_order", "none"]


class PolicyConfig(BaseModel):
    policy_id: str
    policy_version: str
    effective_from: datetime
    effective_to: datetime | None = None
    active: bool = True
    auto_release_max_value: Decimal = Field(default=Decimal("2500"))
    minimum_confidence: Decimal = Field(default=Decimal("0.75"))
    maximum_inventory_age_hours: int = Field(default=336, ge=1)
    maximum_days_of_supply: Decimal = Field(default=Decimal("14"))
    minimum_history_days: int = Field(default=7, ge=0)
    require_review_for_stockout: bool = True
    require_review_for_overstock: bool = True
    require_review_for_promotion_overlap: bool = True
    maximum_override_percent: Decimal = Field(default=Decimal("25"))
    require_formal_approval_above_value: Decimal = Field(default=Decimal("5000"))
    created_by: str = "system"
    created_at: datetime

    @field_validator(
        "auto_release_max_value",
        "minimum_confidence",
        "maximum_days_of_supply",
        "maximum_override_percent",
        "require_formal_approval_above_value",
        mode="before",
    )
    @classmethod
    def _to_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))


class PolicyRuleOutcome(BaseModel):
    rule_name: str
    observed_value: Any = None
    threshold: Any = None
    result: RuleResult
    action: RuleAction = "none"
    explanation: str


class PolicyEvaluationResult(BaseModel):
    disposition: Disposition
    passed: bool
    failed_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evaluated_rules: list[PolicyRuleOutcome] = Field(default_factory=list)
    policy_version: str
    policy_id: str | None = None
    recommendation_status: str | None = None
    order_value: Decimal | None = None
    confidence: Decimal | None = None

    @field_validator("order_value", "confidence", mode="before")
    @classmethod
    def _optional_decimal(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

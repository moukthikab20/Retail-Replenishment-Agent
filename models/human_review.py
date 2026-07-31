"""Human replenishment review domain model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class HumanReplenishmentReview(BaseModel):
    review_id: str
    recommendation_id: str
    agent_recommended_quantity: int = Field(ge=0)
    human_proposed_quantity: int = Field(ge=0)
    override_used: bool
    override_reason: str | None = None
    difference_units: int
    difference_percent: Decimal
    projected_days_of_supply: Decimal | None = None
    projected_risk: str
    requires_escalation: bool
    submitted_by: str
    submitted_at: datetime
    status: str = "submitted"
    validation_messages: list[str] = Field(default_factory=list)
    approval_level: str = "normal"
    nearest_lower_case_pack: int | None = None
    nearest_higher_case_pack: int | None = None
    case_pack_compliant: bool = True

    @field_validator("difference_percent", mode="before")
    @classmethod
    def _to_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @field_validator("projected_days_of_supply", mode="before")
    @classmethod
    def _optional_decimal(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

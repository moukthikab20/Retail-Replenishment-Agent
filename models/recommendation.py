"""Agent recommendation domain model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class Recommendation(BaseModel):
    recommendation_id: str
    store_id: str
    sku: str
    forecast_units: Decimal
    available_units: int = Field(ge=0)
    agent_recommended_quantity: int = Field(ge=0)
    risk_level: str
    rationale: str
    created_at: datetime
    status: str = "pending_review"

    @field_validator("forecast_units", mode="before")
    @classmethod
    def _to_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))

"""Replenishment calculation domain model."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ReplenishmentResult(BaseModel):
    store_id: str
    sku: str
    raw_quantity: Decimal
    recommended_quantity: int = Field(ge=0)
    case_pack: int = Field(gt=0)
    rounding_adjustment: int = 0
    constraints_applied: list[str] = Field(default_factory=list)
    usable_on_hand: int = 0
    in_transit: int = 0
    safety_stock: int = 0
    forecast_units: Decimal = Decimal("0")
    days_of_supply: Decimal | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_quantity", "forecast_units", mode="before")
    @classmethod
    def _to_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @field_validator("days_of_supply", mode="before")
    @classmethod
    def _optional_decimal(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

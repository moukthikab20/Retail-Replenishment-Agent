"""Forecast domain model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class ForecastResult(BaseModel):
    store_id: str
    sku: str
    forecast_days: int = Field(gt=0)
    average_daily_sales: Decimal
    forecast_units: Decimal
    method: str = "trailing_average"
    generated_at: datetime

    @field_validator("average_daily_sales", "forecast_units", mode="before")
    @classmethod
    def _to_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))

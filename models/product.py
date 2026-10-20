"""Product master domain model."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class Product(BaseModel):
    sku: str
    product_name: str
    unit_cost: Decimal = Field(default=Decimal("0.00"))
    case_pack: int = Field(gt=0)
    minimum_order_quantity: int = Field(ge=0, default=0)
    maximum_order_quantity: int = Field(gt=0)
    safety_stock_units: int = Field(ge=0, default=0)
    # Optional shelf face/capacity cap (units). When set, order qty is reduced so
    # usable_on_hand + in_transit + recommended_quantity does not exceed capacity.
    shelf_capacity: int | None = Field(default=None, ge=0)
    category: str | None = None
    vendor_id: str | None = None
    vendor_name: str | None = None

    @field_validator("unit_cost", mode="before")
    @classmethod
    def _to_decimal(cls, value: object) -> Decimal:
        return Decimal(str(value))

    @field_validator("maximum_order_quantity")
    @classmethod
    def _max_gte_min(cls, value: int, info) -> int:
        minimum = info.data.get("minimum_order_quantity", 0)
        if value < minimum:
            raise ValueError("maximum_order_quantity must be >= minimum_order_quantity")
        return value

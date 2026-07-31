"""Inventory position domain model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class InventoryPosition(BaseModel):
    store_id: str
    sku: str
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0, default=0)
    in_transit: int = Field(ge=0, default=0)
    safety_stock: int = Field(ge=0, default=0)
    updated_at: datetime
    store_name: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def usable_on_hand(self) -> int:
        return max(self.on_hand - self.reserved, 0)

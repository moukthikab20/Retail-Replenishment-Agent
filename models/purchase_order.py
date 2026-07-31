"""Mock purchase order domain model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PurchaseOrder(BaseModel):
    purchase_order_id: str
    approval_id: str
    store_id: str
    sku: str
    agent_recommended_quantity: int = Field(ge=0)
    human_proposed_quantity: int = Field(ge=0)
    approved_final_quantity: int = Field(ge=0)
    override_used: bool
    override_reason: str | None = None
    status: str = "Draft — Mock ERP"
    created_at: datetime

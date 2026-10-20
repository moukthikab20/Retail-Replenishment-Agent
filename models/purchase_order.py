"""Purchase order domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PurchaseOrder(BaseModel):
    purchase_order_id: str
    approval_id: str
    recommendation_id: str | None = None
    store_id: str
    sku: str
    agent_recommended_quantity: int = Field(ge=0)
    human_proposed_quantity: int = Field(ge=0)
    approved_final_quantity: int = Field(ge=0)
    override_used: bool
    override_reason: str | None = None
    status: str = "queued_for_erp"
    order_status: str = "queued_for_erp"
    transmission_status: str = "draft"
    transmitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    erp_reference: str | None = None
    external_order_id: str | None = None
    erp_provider: str | None = None
    transmission_error: str | None = None
    last_error_code: str | None = None
    attempt_count: int = 0
    transmission_idempotency_key: str | None = None
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    vendor: str | None = "Demo Vendor"
    amount: float | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)
    source_run_id: str | None = None
    approved_by: str | None = None
    created_at: datetime
    idempotency_key: str | None = None
    user_id: str | None = None
    session_id: str | None = None

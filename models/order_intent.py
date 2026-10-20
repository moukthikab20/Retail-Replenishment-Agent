"""Order intent / purchase-order lifecycle domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Canonical + legacy statuses accepted on the model.
OrderLifecycleStatus = Literal[
    "queued_for_erp",
    "transmitting",
    "erp_acknowledged",
    "completed",
    "transmission_failed",
    "retry_pending",
    "erp_rejected",
    "cancelled",
    # legacy
    "pending_erp",
    "transmitted",
    "acknowledged",
    "in_transit",
    "received",
    "failed",
]

ReleasedByType = Literal["agent_policy", "human"]


class OrderLine(BaseModel):
    line_number: int = 1
    sku: str
    store_id: str
    product_name: str | None = None
    quantity: int = Field(ge=0)
    unit_cost: float = 0.0
    line_amount: float = 0.0


class OrderIntent(BaseModel):
    order_intent_id: str
    recommendation_id: str
    approval_id: str | None = None
    purchase_order_id: str | None = None
    status: OrderLifecycleStatus = "queued_for_erp"
    store_id: str
    sku: str
    product_name: str | None = None
    quantity: int = Field(ge=0)
    unit_cost: float = 0.0
    amount: float = 0.0
    vendor: str = "Demo Vendor"
    lines: list[OrderLine] = Field(default_factory=list)
    source_run_id: str | None = None
    approved_by: str | None = None
    released_by_type: ReleasedByType = "human"
    released_by_label: str | None = None
    idempotency_key: str
    transmission_idempotency_key: str | None = None
    mock_erp_reference: str | None = None
    external_order_id: str | None = None
    erp_provider: str | None = None
    transmitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    last_error: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    attempts: int = 0
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    user_id: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    execution_id: str | None = None

"""Domain models for batch replenishment runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

RunStatus = Literal[
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
]
TriggerType = Literal["scheduled", "manual", "retry"]
Disposition = Literal["auto_release", "human_review", "blocked", "no_order"]
RunItemStatus = Literal["pending", "scored", "failed", "skipped"]


class ReplenishmentRun(BaseModel):
    run_id: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: RunStatus = "pending"
    trigger_type: TriggerType = "manual"
    initiated_by: str = "system"
    total_items: int = Field(default=0, ge=0)
    scored_items: int = Field(default=0, ge=0)
    auto_released_items: int = Field(default=0, ge=0)
    review_items: int = Field(default=0, ge=0)
    blocked_items: int = Field(default=0, ge=0)
    no_order_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    policy_version: str = "v1"
    model_name: str | None = None
    error_summary: str | None = None
    created_at: datetime
    invocation_key: str | None = None
    scheduled_for: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def processed_items(self) -> int:
        """Alias for scored_items (checkpoint contract)."""
        return self.scored_items

    @computed_field  # type: ignore[prop-decorator]
    @property
    def human_review_items(self) -> int:
        """Alias for review_items (checkpoint contract)."""
        return self.review_items

    @computed_field  # type: ignore[prop-decorator]
    @property
    def agent_model(self) -> str | None:
        """Alias for model_name (checkpoint contract)."""
        return self.model_name


class ReplenishmentRunItem(BaseModel):
    item_id: str
    run_id: str
    store_id: str
    sku: str
    status: RunItemStatus = "pending"
    disposition: Disposition | None = None
    recommendation_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class BatchRunResult(BaseModel):
    """Typed contract for run_replenishment_batch outcomes (dict via to_dict())."""

    run_id: str
    status: RunStatus
    trigger_type: TriggerType = "manual"
    initiated_by: str = "system"
    total_items: int = 0
    scored_items: int = 0
    processed_items: int = 0
    auto_released_items: int = 0
    review_items: int = 0
    human_review_items: int = 0
    blocked_items: int = 0
    no_order_items: int = 0
    failed_items: int = 0
    policy_version: str = "v1"
    model_name: str | None = None
    agent_model: str | None = None
    error_summary: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None
    errors: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    idempotent_replay: bool = False
    orders_queued: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

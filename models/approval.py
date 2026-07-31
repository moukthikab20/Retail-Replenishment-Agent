"""Approval request domain model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ApprovalRequest(BaseModel):
    approval_id: str
    review_id: str
    recommendation_id: str
    agent_recommended_quantity: int = Field(ge=0)
    human_proposed_quantity: int = Field(ge=0)
    approved_final_quantity: int | None = None
    required_role: str
    status: str = "pending"
    requested_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None

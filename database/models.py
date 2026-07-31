"""SQLAlchemy ORM models for persisted workflow entities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RecommendationRow(Base):
    __tablename__ = "recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    forecast_units: Mapped[float] = mapped_column(Float, nullable=False)
    available_units: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review")
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    usable_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_transit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_of_supply: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    case_pack: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    average_daily_sales: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class HumanReviewRow(Base):
    __tablename__ = "human_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    human_proposed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    override_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    difference_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    difference_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    projected_days_of_supply: Mapped[float | None] = mapped_column(Float, nullable=True)
    projected_risk: Mapped[str] = mapped_column(String(32), nullable=False)
    requires_escalation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_by: Mapped[str] = mapped_column(String(128), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    approval_level: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    validation_messages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    case_pack_compliant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    nearest_lower_case_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nearest_higher_case_pack: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    human_proposed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_final_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class PurchaseOrderRow(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("approval_id", name="uq_po_approval_id"),)

    purchase_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    human_proposed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_final_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    override_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="Draft — Mock ERP")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    review_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchase_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class AgentRunStateRow(Base):
    __tablename__ = "agent_run_states"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="paused")
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    pending_tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_tool_args_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

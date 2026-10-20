"""SQLAlchemy ORM models for persisted workflow entities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ReplenishmentRunRow(Base):
    """Batch scoring run over many store/SKU combinations."""

    __tablename__ = "replenishment_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    initiated_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_released_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_order_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Deterministic scheduler bucket key, e.g. scheduled:2026-08-12T06:00:00+00:00
    invocation_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SchedulerLockRow(Base):
    """Cross-process lease for exclusive replenishment batch execution."""

    __tablename__ = "scheduler_locks"

    lock_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ReplenishmentRunItemRow(Base):
    """Per store/SKU outcome within a batch run (idempotent by run+store+sku)."""

    __tablename__ = "replenishment_run_items"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "store_id",
            "sku",
            name="uq_run_item_run_store_sku",
        ),
    )

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PolicyConfigRow(Base):
    """Versioned replenishment release policy (deterministic; not model-owned)."""

    __tablename__ = "policy_configs"
    __table_args__ = (
        UniqueConstraint("policy_version", name="uq_policy_configs_version"),
    )

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_release_max_value: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    maximum_inventory_age_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_days_of_supply: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_history_days: Mapped[int] = mapped_column(Integer, nullable=False)
    require_review_for_stockout: Mapped[bool] = mapped_column(Boolean, nullable=False)
    require_review_for_overstock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    require_review_for_promotion_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False)
    maximum_override_percent: Mapped[float] = mapped_column(Float, nullable=False)
    require_formal_approval_above_value: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RecommendationRow(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "store_id",
            "sku",
            name="uq_recommendation_run_store_sku",
        ),
    )

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
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_evaluation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    usable_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_transit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_of_supply: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    case_pack: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    average_daily_sales: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    recommendation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    declined_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    declined_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decline_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class HumanReviewRow(Base):
    __tablename__ = "human_reviews"

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    human_proposed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    override_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="agent"
    )
    ai_recommendation_unavailable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
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
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("review_id", name="uq_approval_review_id"),)

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
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class PurchaseOrderRow(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("approval_id", name="uq_po_approval_id"),
        UniqueConstraint("idempotency_key", name="uq_po_idempotency_key"),
    )

    purchase_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    store_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_recommended_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    human_proposed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_final_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    override_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="queued_for_erp")
    order_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued_for_erp", index=True
    )
    transmission_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", index=True
    )
    transmitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    erp_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    erp_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transmission_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transmission_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Stable key for retry-safe order execution (defaults to approval_id)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class OrderIntentRow(Base):
    """Approved order waiting for / progressing through ERP transmission."""

    __tablename__ = "order_intents"
    __table_args__ = (
        UniqueConstraint("recommendation_id", name="uq_order_intent_recommendation_id"),
        UniqueConstraint("idempotency_key", name="uq_order_intent_idempotency_key"),
        UniqueConstraint(
            "transmission_idempotency_key",
            name="uq_order_intent_transmission_idempotency_key",
        ),
    )

    order_intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    purchase_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued_for_erp", index=True
    )
    store_id: Mapped[str] = mapped_column(String(32), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    vendor: Mapped[str] = mapped_column(String(128), nullable=False, default="Demo Vendor")
    lines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    released_by_type: Mapped[str] = mapped_column(String(32), nullable=False, default="human")
    released_by_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    transmission_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mock_erp_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    erp_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transmitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class ErpOutboxRow(Base):
    """Outbound purchase-order transmission queue (mock or real ERP adapter)."""

    __tablename__ = "erp_outbox"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", name="uq_erp_outbox_purchase_order_id"),
    )

    outbox_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    purchase_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    erp_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    review_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchase_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    actor_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    store_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class AgentRunStateRow(Base):
    """Durable agent execution record (HITL + general Goal→Plan→Tool flows)."""

    __tablename__ = "agent_run_states"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_agent_run_idempotency_key"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="paused")
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    pending_tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_tool_args_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Optional stable key for retry-safe order/HITL execution
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Additive durable-execution fields (20260811_0010)
    execution_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    current_step: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    waiting_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FollowUpSessionMessageRow(Base):
    """Conversational memory for follow-up Q&A — not authoritative business state."""

    __tablename__ = "agent_follow_up_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class KnowledgeDocumentRow(Base):
    """Semantic knowledge corpus document (prose policies/SOPs/guides)."""

    __tablename__ = "knowledge_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    access_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="public", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    store_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class KnowledgeChunkRow(Base):
    """Deterministic chunks for semantic retrieval."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_doc_idx"),
    )

    chunk_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    embedding_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Local vector implementation only — not a commercial vector DB.
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Denormalized filters for retrieval without joining every time.
    access_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="public", index=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    store_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

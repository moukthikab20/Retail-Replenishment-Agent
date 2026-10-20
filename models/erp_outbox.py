"""ERP outbox and transmit result domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

OutboxStatus = Literal["pending", "sent", "failed"]
TransmissionStatus = Literal["draft", "queued", "sent", "failed"]

ERP_OUTCOME_ACCEPTED = "accepted"
ERP_OUTCOME_REJECTED = "rejected"
ERP_OUTCOME_TEMPORARY_FAILURE = "temporary_failure"
ERP_OUTCOME_TIMEOUT = "timeout"


class ERPTransmissionResult(BaseModel):
    """Production-facing ERP adapter transmit contract."""

    success: bool = False
    status: str = ERP_OUTCOME_TEMPORARY_FAILURE
    external_order_id: str | None = None
    provider_reference: str | None = None
    acknowledgement_code: str | None = None
    message: str | None = None
    submitted_at: datetime | None = None
    acknowledged_at: datetime | None = None
    retryable: bool = False
    provider_name: str = "Mock ERP"
    provider_request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    # Legacy fields (kept for older callers / adapters)
    ok: bool | None = None
    erp_reference: str | None = None
    error: str | None = None
    adapter: str = "mock"

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "success" not in payload and "ok" in payload:
            payload["success"] = bool(payload.get("ok"))
        if payload.get("external_order_id") is None and payload.get("erp_reference"):
            payload["external_order_id"] = payload.get("erp_reference")
        if payload.get("provider_reference") is None and payload.get("erp_reference"):
            payload["provider_reference"] = payload.get("erp_reference")
        if payload.get("error_message") is None and payload.get("error"):
            payload["error_message"] = payload.get("error")
        if payload.get("message") is None and payload.get("error"):
            payload["message"] = payload.get("error")
        raw = dict(payload.get("raw") or {})
        if payload.get("adapter"):
            raw.setdefault("adapter", payload["adapter"])
        payload["raw"] = raw
        # Derive status when only ok provided
        if "status" not in payload or payload.get("status") in {None, ""}:
            if payload.get("success"):
                payload["status"] = ERP_OUTCOME_ACCEPTED
            elif payload.get("retryable") is False:
                payload["status"] = ERP_OUTCOME_REJECTED
            else:
                payload["status"] = ERP_OUTCOME_TEMPORARY_FAILURE
        return payload

    @model_validator(mode="after")
    def _sync_legacy_fields(self) -> ERPTransmissionResult:
        object.__setattr__(self, "ok", self.success)
        ref = self.external_order_id or self.provider_reference
        object.__setattr__(self, "erp_reference", ref)
        object.__setattr__(
            self,
            "error",
            self.error_message or (None if self.success else self.message),
        )
        adapter = (self.raw or {}).get("adapter") or self.adapter or "mock"
        object.__setattr__(self, "adapter", adapter)
        if self.retryable is False and not self.success and self.status == ERP_OUTCOME_TEMPORARY_FAILURE:
            # keep explicit retryable from caller; default temporary failures to retryable
            if self.error_code in {None, "erp_temporary_failure", "erp_timeout"}:
                object.__setattr__(self, "retryable", True)
        if not self.success and self.status == ERP_OUTCOME_REJECTED:
            object.__setattr__(self, "retryable", False)
        return self


# Backward-compatible alias
ErpTransmitResult = ERPTransmissionResult


class ErpOutboxEntry(BaseModel):
    outbox_id: str
    purchase_order_id: str
    run_id: str | None = None
    batch_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: OutboxStatus = "pending"
    attempts: int = 0
    last_error: str | None = None
    erp_reference: str | None = None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None

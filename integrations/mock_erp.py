"""Mock ERP adapter — in-process only; no network calls.

Supports deterministic scenarios via payload['mock_scenario'] or constructor:
  success | temporary_failure | business_rejection | timeout
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from config import ERP_MOCK_FORCE_FAIL, ERP_MOCK_SCENARIO
from integrations.contracts import ProviderHealth
from integrations.failures import ProviderFailureCode, ProviderError
from models.erp_outbox import (
    ERP_OUTCOME_ACCEPTED,
    ERP_OUTCOME_REJECTED,
    ERP_OUTCOME_TEMPORARY_FAILURE,
    ERP_OUTCOME_TIMEOUT,
    ERPTransmissionResult,
    ErpTransmitResult,
)

ADAPTER_MOCK = "mock"
SOURCE_LABEL = "Mock ERP"
PROVIDER_NAME = "Mock ERP"

_VALID_SCENARIOS = {
    "success",
    "temporary_failure",
    "business_rejection",
    "timeout",
}


class MockERPAdapter:
    """Preserves existing mock transmit behavior behind ERPAdapter."""

    name = ADAPTER_MOCK
    provider_name = PROVIDER_NAME
    source_label = SOURCE_LABEL

    def __init__(
        self,
        *,
        force_fail: bool | None = None,
        scenario: str | None = None,
    ) -> None:
        self.force_fail = ERP_MOCK_FORCE_FAIL if force_fail is None else force_fail
        self.default_scenario = (scenario or ERP_MOCK_SCENARIO or "success").strip().lower()
        if self.default_scenario not in _VALID_SCENARIOS:
            self.default_scenario = "success"
        self._status_by_ref: dict[str, dict[str, Any]] = {}
        # transmission_idempotency_key → prior successful result
        self._idempotent_results: dict[str, ERPTransmissionResult] = {}

    def health_check(self) -> ProviderHealth:
        ok = not self.force_fail
        return ProviderHealth(
            ok=ok,
            status="healthy" if ok else "unavailable",
            provider_name=self.provider_name,
            source=self.source_label,
            message=(
                "Mock ERP forced into failure mode"
                if self.force_fail
                else "Mock ERP ready (no external network)."
            ),
            details={
                "adapter": self.name,
                "mode": "mock",
                "real_erp": False,
                "scenario": self.default_scenario,
            },
        )

    def health(self) -> dict[str, Any]:
        check = self.health_check()
        return {
            "ok": check.ok,
            "adapter": self.name,
            "provider_name": self.provider_name,
            "source": self.source_label,
            "mode": "mock",
            "real_erp": False,
            "detail": check.message,
            "status": check.status,
        }

    def _resolve_scenario(self, payload: dict[str, Any]) -> str:
        if self.force_fail:
            return "temporary_failure"
        raw = str(payload.get("mock_scenario") or self.default_scenario or "success").strip().lower()
        return raw if raw in _VALID_SCENARIOS else "success"

    def transmit(self, payload: dict[str, Any]) -> ErpTransmitResult:
        now = datetime.now(timezone.utc)
        idem_key = (
            payload.get("transmission_idempotency_key")
            or payload.get("idempotency_key")
            or ""
        )
        if idem_key and idem_key in self._idempotent_results:
            prior = self._idempotent_results[idem_key]
            # Return a copy so callers cannot mutate the cached result.
            return ErpTransmitResult(**prior.model_dump())

        scenario = self._resolve_scenario(payload)
        request_id = f"MOCK-REQ-{uuid4().hex[:10].upper()}"

        if scenario == "temporary_failure":
            return ErpTransmitResult(
                success=False,
                status=ERP_OUTCOME_TEMPORARY_FAILURE,
                message="Mock ERP temporarily unavailable",
                retryable=True,
                provider_name=self.provider_name,
                provider_request_id=request_id,
                error_code="erp_temporary_failure",
                error_message="Mock ERP temporarily unavailable",
                submitted_at=now,
                raw={
                    "adapter": self.name,
                    "scenario": scenario,
                    "payload_keys": sorted(payload.keys()),
                    "source": self.source_label,
                    "provider_name": self.provider_name,
                },
            )

        if scenario == "timeout":
            return ErpTransmitResult(
                success=False,
                status=ERP_OUTCOME_TIMEOUT,
                message="Mock ERP request timed out",
                retryable=True,
                provider_name=self.provider_name,
                provider_request_id=request_id,
                error_code="erp_timeout",
                error_message="Mock ERP request timed out",
                submitted_at=now,
                raw={
                    "adapter": self.name,
                    "scenario": scenario,
                    "source": self.source_label,
                    "provider_name": self.provider_name,
                },
            )

        if scenario == "business_rejection":
            return ErpTransmitResult(
                success=False,
                status=ERP_OUTCOME_REJECTED,
                message="Mock ERP rejected order (invalid supplier/SKU/location)",
                retryable=False,
                provider_name=self.provider_name,
                provider_request_id=request_id,
                error_code="erp_business_rejected",
                error_message="Mock ERP rejected order (invalid supplier/SKU/location)",
                submitted_at=now,
                raw={
                    "adapter": self.name,
                    "scenario": scenario,
                    "rejection_reason": "invalid_supplier_or_sku",
                    "source": self.source_label,
                    "provider_name": self.provider_name,
                },
            )

        # success
        po_id = payload.get("purchase_order_id") or f"PO-MOCK-{uuid4().hex[:8].upper()}"
        # Stable external id when idempotency key present
        if idem_key:
            digest = uuid4().hex[:10].upper() if idem_key not in self._idempotent_results else ""
            # Prefer deterministic id from key so retries reuse the same ERP order.
            import hashlib

            digest = hashlib.sha256(idem_key.encode("utf-8")).hexdigest()[:10].upper()
            reference = f"ERP-MOCK-{digest}"
        else:
            reference = f"ERP-MOCK-{uuid4().hex[:10].upper()}"
        vendor = payload.get("vendor") or "Demo Vendor Co."
        lines = payload.get("lines") or [
            {
                "line_number": 1,
                "sku": payload.get("sku"),
                "store_id": payload.get("store_id"),
                "quantity": payload.get("approved_final_quantity")
                or payload.get("quantity"),
                "unit_cost": payload.get("unit_cost"),
                "line_amount": payload.get("amount"),
            }
        ]
        amount = payload.get("amount")
        if amount is None:
            try:
                amount = float(payload.get("unit_cost") or 0) * float(
                    payload.get("approved_final_quantity")
                    or payload.get("quantity")
                    or 0
                )
            except (TypeError, ValueError):
                amount = 0.0
        response = {
            "purchase_order_id": po_id,
            "transmitted_at": now.isoformat(),
            "acknowledged_at": now.isoformat(),
            "vendor": vendor,
            "lines": lines,
            "amount": float(amount or 0),
            "status": "accepted",
            "mock_erp_reference": reference,
            "external_order_id": reference,
            "acknowledged": True,
            "acknowledgement_code": "ACK",
            "source": self.source_label,
            "provider_name": self.provider_name,
            "adapter": self.name,
            "transmission_idempotency_key": idem_key or None,
            "provider_request_id": request_id,
            "scenario": scenario,
        }
        self._status_by_ref[reference] = {
            "erp_reference": reference,
            "external_order_id": reference,
            "status": "acknowledged",
            "purchase_order_id": po_id,
            "acknowledged": True,
            "acknowledged_at": now.isoformat(),
            "source": self.source_label,
            "provider_name": self.provider_name,
            "updated_at": now.isoformat(),
        }
        result = ErpTransmitResult(
            success=True,
            status=ERP_OUTCOME_ACCEPTED,
            external_order_id=reference,
            provider_reference=reference,
            acknowledgement_code="ACK",
            message="Mock ERP accepted and acknowledged order",
            submitted_at=now,
            acknowledged_at=now,
            retryable=False,
            provider_name=self.provider_name,
            provider_request_id=request_id,
            raw=response,
        )
        if idem_key:
            self._idempotent_results[idem_key] = result
        return result

    def get_order_status(self, erp_reference: str) -> dict[str, Any]:
        known = self._status_by_ref.get(erp_reference)
        if known is not None:
            return known
        return {
            "erp_reference": erp_reference,
            "status": "unknown",
            "acknowledged": False,
            "source": self.source_label,
            "provider_name": self.provider_name,
            "message": "No mock acknowledgement recorded for this reference.",
        }

    def queue_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Not an ERP transmit — OrderIntent queueing remains a business concern."""
        raise ProviderError(
            code=ProviderFailureCode.NOT_IMPLEMENTED.value,
            message=(
                "queue_order is owned by OrderIntent / order lifecycle services; "
                "ERP adapters only transmit already-queued approved orders."
            ),
            provider=self.provider_name,
            details={"payload_keys": sorted(payload.keys())},
        )

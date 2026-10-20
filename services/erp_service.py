"""ERP adapter facade — delegates to integrations factory.

Business services must not import MockERPAdapter directly for new code.
Legacy tests may still reference erp_service.MockErpAdapter.
"""

from __future__ import annotations

from typing import Any

from integrations.factory import get_erp_adapter as _factory_get_erp_adapter
from integrations.factory import reset_providers
from integrations.mock_erp import ADAPTER_MOCK, MockERPAdapter
from models.erp_outbox import ErpTransmitResult

# Backward-compatible alias (historical camel casing in tests).
MockErpAdapter = MockERPAdapter

__all__ = [
    "ADAPTER_MOCK",
    "MockERPAdapter",
    "MockErpAdapter",
    "adapter_health",
    "get_erp_adapter",
    "reset_erp_adapter",
    "transmit_purchase_order_payload",
]


def get_erp_adapter(*, force_new: bool = False):
    """Return the configured ERP adapter (fail-fast on unknown ERP_PROVIDER)."""
    return _factory_get_erp_adapter(force_new=force_new)


def reset_erp_adapter() -> None:
    """Test helper — clear cached provider instances including ERP."""
    reset_providers()


def adapter_health() -> dict[str, Any]:
    adapter = get_erp_adapter()
    if hasattr(adapter, "health"):
        payload = adapter.health()
    else:
        check = adapter.health_check()
        payload = {
            "ok": check.ok,
            "adapter": getattr(adapter, "name", ADAPTER_MOCK),
            "provider_name": check.provider_name,
            "source": check.source,
            "real_erp": False,
            "detail": check.message,
            "status": check.status,
        }
    payload.setdefault("adapter", getattr(adapter, "name", ADAPTER_MOCK))
    payload.setdefault(
        "provider_name", getattr(adapter, "provider_name", payload.get("adapter"))
    )
    payload.setdefault("source", getattr(adapter, "source_label", "Mock ERP"))
    payload.setdefault("real_erp", False)
    return payload


def transmit_purchase_order_payload(payload: dict[str, Any]) -> ErpTransmitResult:
    """Transmit via the active adapter. Does not mutate database state."""
    return get_erp_adapter().transmit(payload)

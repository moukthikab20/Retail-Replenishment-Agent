"""Provider registry / factory — single configuration path for adapters."""

from __future__ import annotations

from typing import Any

from config import (
    ERP_ADAPTER,
    ERP_MOCK_FORCE_FAIL,
    ERP_PROVIDER,
    INVENTORY_PROVIDER,
    PRODUCT_PROVIDER,
    SALES_PROVIDER,
    SUPPLIER_PROVIDER,
)
from integrations.contracts import (
    ERPAdapter,
    InventoryProvider,
    ProductProvider,
    ProviderHealth,
    SalesProvider,
    SupplierProvider,
)
from integrations.csv_inventory import CSVInventoryProvider
from integrations.csv_product import CSVProductProvider
from integrations.csv_sales import CSVSalesProvider
from integrations.demo_supplier import DemoSupplierProvider
from integrations.failures import ProviderConfigError
from integrations.mock_erp import MockERPAdapter

_SUPPORTED = {
    "inventory": {"csv": CSVInventoryProvider},
    "sales": {"csv": CSVSalesProvider},
    "product": {"csv": CSVProductProvider},
    "supplier": {"demo": DemoSupplierProvider},
    "erp": {"mock": MockERPAdapter},
}

_inventory: InventoryProvider | None = None
_sales: SalesProvider | None = None
_product: ProductProvider | None = None
_supplier: SupplierProvider | None = None
_erp: ERPAdapter | None = None
_validated = False


def _erp_provider_key() -> str:
    # Prefer ERP_PROVIDER; fall back to legacy ERP_ADAPTER.
    return (ERP_PROVIDER or ERP_ADAPTER or "mock").strip().lower()


def validate_provider_configuration() -> dict[str, str]:
    """Fail fast on unknown provider values. No silent fallback."""
    global _validated
    selected = {
        "inventory": (INVENTORY_PROVIDER or "csv").strip().lower(),
        "sales": (SALES_PROVIDER or "csv").strip().lower(),
        "product": (PRODUCT_PROVIDER or "csv").strip().lower(),
        "supplier": (SUPPLIER_PROVIDER or "demo").strip().lower(),
        "erp": _erp_provider_key(),
    }
    for key, value in selected.items():
        allowed = _SUPPORTED[key]
        if value not in allowed:
            available = ", ".join(sorted(allowed))
            label = {
                "inventory": "Inventory",
                "sales": "Sales",
                "product": "Product",
                "supplier": "Supplier",
                "erp": "ERP",
            }[key]
            raise ProviderConfigError(
                f"{label} provider '{value}' is not available in this deployment. "
                f"Supported: {available}.",
                provider_key=key,
            )
    _validated = True
    return selected


def _ensure_validated() -> None:
    if not _validated:
        validate_provider_configuration()


def get_inventory_provider(*, force_new: bool = False) -> InventoryProvider:
    global _inventory
    _ensure_validated()
    if _inventory is None or force_new:
        key = (INVENTORY_PROVIDER or "csv").strip().lower()
        _inventory = _SUPPORTED["inventory"][key]()
    return _inventory


def get_sales_provider(*, force_new: bool = False) -> SalesProvider:
    global _sales
    _ensure_validated()
    if _sales is None or force_new:
        key = (SALES_PROVIDER or "csv").strip().lower()
        _sales = _SUPPORTED["sales"][key]()
    return _sales


def get_product_provider(*, force_new: bool = False) -> ProductProvider:
    global _product
    _ensure_validated()
    if _product is None or force_new:
        key = (PRODUCT_PROVIDER or "csv").strip().lower()
        _product = _SUPPORTED["product"][key]()
    return _product


def get_supplier_provider(*, force_new: bool = False) -> SupplierProvider:
    global _supplier
    _ensure_validated()
    if _supplier is None or force_new:
        key = (SUPPLIER_PROVIDER or "demo").strip().lower()
        _supplier = _SUPPORTED["supplier"][key]()
    return _supplier


def get_erp_adapter(*, force_new: bool = False) -> ERPAdapter:
    global _erp
    _ensure_validated()
    if _erp is None or force_new:
        key = _erp_provider_key()
        cls = _SUPPORTED["erp"][key]
        if cls is MockERPAdapter:
            _erp = MockERPAdapter(force_fail=ERP_MOCK_FORCE_FAIL)
        else:
            _erp = cls()
    return _erp


def reset_providers() -> None:
    """Test helper — clear cached provider instances and validation flag."""
    global _inventory, _sales, _product, _supplier, _erp, _validated
    _inventory = None
    _sales = None
    _product = None
    _supplier = None
    _erp = None
    _validated = False


def get_provider_summary() -> dict[str, Any]:
    """Read-only configuration + health snapshot for Admin / Health UI."""
    selected = validate_provider_configuration()
    healths: dict[str, ProviderHealth] = {
        "inventory": get_inventory_provider().health_check(),
        "sales": get_sales_provider().health_check(),
        "product": get_product_provider().health_check(),
        "supplier": get_supplier_provider().health_check(),
        "erp": get_erp_adapter().health_check(),
    }
    return {
        "selected": selected,
        "providers": {
            key: {
                "config": selected[key],
                "provider_name": healths[key].provider_name,
                "source": healths[key].source,
                "status": healths[key].status,
                "ok": healths[key].ok,
                "message": healths[key].message,
            }
            for key in selected
        },
    }


def provider_health_checks() -> list[dict[str, Any]]:
    summary = get_provider_summary()
    rows = []
    labels = {
        "inventory": "Inventory Provider",
        "sales": "Sales Provider",
        "product": "Product Provider",
        "supplier": "Supplier Provider",
        "erp": "ERP Provider",
    }
    for key, label in labels.items():
        row = summary["providers"][key]
        rows.append(
            {
                "component": f"provider_{key}",
                "label": label,
                "purpose": f"External {key} data access via configured adapter.",
                "status": row["status"] if row["ok"] or row["status"] != "healthy" else row["status"],
                "provider_name": row["provider_name"],
                "source": row["source"],
                "config": row["config"],
                "message": row["message"],
                "ok": row["ok"],
            }
        )
    return rows

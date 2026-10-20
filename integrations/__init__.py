"""Enterprise integration provider layer.

Business services depend on provider interfaces; CSV / demo / mock adapters
implement those interfaces. Agent tools must not call providers directly.
"""

from __future__ import annotations

from integrations.factory import (
    get_erp_adapter,
    get_inventory_provider,
    get_product_provider,
    get_provider_summary,
    get_sales_provider,
    get_supplier_provider,
    reset_providers,
    validate_provider_configuration,
)

__all__ = [
    "get_erp_adapter",
    "get_inventory_provider",
    "get_product_provider",
    "get_provider_summary",
    "get_sales_provider",
    "get_supplier_provider",
    "reset_providers",
    "validate_provider_configuration",
]

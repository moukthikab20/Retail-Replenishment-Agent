"""Provider contracts and typed result models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from models.erp_outbox import ErpTransmitResult
from models.inventory import InventoryPosition
from models.product import Product


class ProviderHealth(BaseModel):
    ok: bool
    status: str = "healthy"  # healthy | degraded | unavailable
    provider_name: str
    source: str
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class InventoryPositionResult(BaseModel):
    position: InventoryPosition
    source: str
    provider_name: str
    freshness_updated_at: datetime | None = None


class SalesDayRecord(BaseModel):
    date: datetime
    units_sold: float


class SalesHistoryResult(BaseModel):
    store_id: str
    sku: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    daily_sales: list[SalesDayRecord] = Field(default_factory=list)
    average_daily_sales: float = 0.0
    source: str
    provider_name: str
    updated_at: datetime | None = None
    history_days: int = 0


class ProductRecord(BaseModel):
    """Product master projection — unsupported demo fields remain None."""

    sku: str
    product_name: str
    case_pack: int
    unit_cost: Decimal
    minimum_order_quantity: int = 0
    maximum_order_quantity: int = 0
    shelf_capacity: int | None = None
    vendor_id: str | None = None
    supplier_lead_time_days: int | None = None
    safety_stock_units: int = 0
    category: str | None = None
    vendor_name: str | None = None
    source: str
    provider_name: str

    def to_product(self) -> Product:
        return Product(
            sku=self.sku,
            product_name=self.product_name,
            unit_cost=self.unit_cost,
            case_pack=self.case_pack,
            minimum_order_quantity=self.minimum_order_quantity,
            maximum_order_quantity=self.maximum_order_quantity,
            safety_stock_units=self.safety_stock_units,
            shelf_capacity=self.shelf_capacity,
            category=self.category,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
        )


class SupplierRecord(BaseModel):
    vendor_id: str
    vendor_name: str
    lead_time_days: int | None = None
    terms: str | None = None
    source: str
    provider_name: str


class SupplierTerms(BaseModel):
    vendor_id: str
    sku: str | None = None
    lead_time_days: int | None = None
    minimum_order_quantity: int | None = None
    currency: str | None = None
    source: str
    provider_name: str


@runtime_checkable
class InventoryProvider(Protocol):
    provider_name: str
    source_label: str

    def get_inventory_position(
        self, store_id: str, sku: str
    ) -> InventoryPositionResult | None: ...

    def get_inventory_snapshot(
        self,
        *,
        store_ids: list[str] | None = None,
        skus: list[str] | None = None,
    ) -> list[InventoryPositionResult]: ...

    def get_inventory_freshness(
        self, store_id: str, sku: str
    ) -> datetime | None: ...

    def health_check(self) -> ProviderHealth: ...


@runtime_checkable
class SalesProvider(Protocol):
    provider_name: str
    source_label: str

    def get_sales_history(
        self,
        store_id: str,
        sku: str,
        *,
        lookback_days: int,
        as_of: datetime | None = None,
    ) -> SalesHistoryResult: ...

    def get_recent_sales(
        self,
        store_id: str,
        sku: str,
        *,
        days: int = 14,
        as_of: datetime | None = None,
    ) -> SalesHistoryResult: ...

    def count_history_days(self, store_id: str, sku: str) -> int: ...

    def health_check(self) -> ProviderHealth: ...


@runtime_checkable
class ProductProvider(Protocol):
    provider_name: str
    source_label: str

    def get_product(self, sku: str) -> ProductRecord | None: ...

    def list_skus_for_store(self, store_id: str) -> list[str]: ...

    def list_stores(self) -> list[dict[str, str]]: ...

    def health_check(self) -> ProviderHealth: ...


@runtime_checkable
class SupplierProvider(Protocol):
    provider_name: str
    source_label: str

    def get_supplier(self, vendor_id: str) -> SupplierRecord | None: ...

    def get_supplier_terms(
        self, vendor_id: str, sku: str | None = None
    ) -> SupplierTerms | None: ...

    def get_expected_lead_time(
        self, vendor_id: str, sku: str | None = None
    ) -> int | None: ...

    def get_default_vendor(self) -> SupplierRecord: ...

    def health_check(self) -> ProviderHealth: ...


@runtime_checkable
class ERPAdapter(Protocol):
    """Outbound ERP transmission. OrderIntent queueing stays in business services."""

    name: str
    provider_name: str
    source_label: str

    def health_check(self) -> ProviderHealth: ...

    def health(self) -> dict[str, Any]: ...

    def transmit(self, payload: dict[str, Any]) -> ErpTransmitResult: ...

    def get_order_status(self, erp_reference: str) -> dict[str, Any]: ...

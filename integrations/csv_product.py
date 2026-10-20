"""CSV-backed product / master-data provider."""

from __future__ import annotations

from pathlib import Path

from integrations.contracts import ProductRecord, ProviderHealth
from repositories import csv_repository

SOURCE_LABEL = "Demo CSV"
PROVIDER_NAME = "CSV Product Provider"


class CSVProductProvider:
    provider_name = PROVIDER_NAME
    source_label = SOURCE_LABEL

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir

    def get_product(self, sku: str) -> ProductRecord | None:
        product = csv_repository.get_product(sku, self._data_dir)
        if product is None:
            return None
        return ProductRecord(
            sku=product.sku,
            product_name=product.product_name,
            case_pack=product.case_pack,
            unit_cost=product.unit_cost,
            minimum_order_quantity=product.minimum_order_quantity,
            maximum_order_quantity=product.maximum_order_quantity,
            shelf_capacity=product.shelf_capacity,
            vendor_id=product.vendor_id,
            supplier_lead_time_days=None,
            safety_stock_units=product.safety_stock_units,
            category=product.category,
            vendor_name=product.vendor_name,
            source=self.source_label,
            provider_name=self.provider_name,
        )

    def list_skus_for_store(self, store_id: str) -> list[str]:
        return csv_repository.list_skus_for_store(store_id, self._data_dir)

    def list_stores(self) -> list[dict[str, str]]:
        return csv_repository.list_stores(self._data_dir)

    def health_check(self) -> ProviderHealth:
        try:
            products, _, _ = csv_repository.get_frames(self._data_dir)
            ok = not products.empty
            return ProviderHealth(
                ok=ok,
                status="healthy" if ok else "degraded",
                provider_name=self.provider_name,
                source=self.source_label,
                message=(
                    f"Product Master — {self.source_label} "
                    f"({len(products)} SKUs)."
                    if ok
                    else f"Product Master — {self.source_label} is empty."
                ),
                details={"sku_count": int(len(products)), "real_master": False},
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                ok=False,
                status="unavailable",
                provider_name=self.provider_name,
                source=self.source_label,
                message=f"Product provider unavailable: {exc}",
                details={"real_master": False},
            )

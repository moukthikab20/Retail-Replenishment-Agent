"""CSV-backed inventory provider."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from integrations.contracts import InventoryPositionResult, ProviderHealth
from repositories import csv_repository

SOURCE_LABEL = "Demo CSV"
PROVIDER_NAME = "CSV Inventory Provider"


class CSVInventoryProvider:
    provider_name = PROVIDER_NAME
    source_label = SOURCE_LABEL

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir

    def get_inventory_position(
        self, store_id: str, sku: str
    ) -> InventoryPositionResult | None:
        position = csv_repository.get_inventory_position(store_id, sku, self._data_dir)
        if position is None:
            return None
        return InventoryPositionResult(
            position=position,
            source=self.source_label,
            provider_name=self.provider_name,
            freshness_updated_at=position.updated_at,
        )

    def get_inventory_snapshot(
        self,
        *,
        store_ids: list[str] | None = None,
        skus: list[str] | None = None,
    ) -> list[InventoryPositionResult]:
        _, inventory, _ = csv_repository.get_frames(self._data_dir)
        frame = inventory
        if store_ids:
            frame = frame.loc[frame["store_id"].isin(store_ids)]
        if skus:
            frame = frame.loc[frame["sku"].isin(skus)]
        results: list[InventoryPositionResult] = []
        for row in frame.itertuples(index=False):
            item = self.get_inventory_position(str(row.store_id), str(row.sku))
            if item is not None:
                results.append(item)
        return results

    def get_inventory_freshness(self, store_id: str, sku: str) -> datetime | None:
        result = self.get_inventory_position(store_id, sku)
        if result is None:
            return None
        return result.freshness_updated_at or result.position.updated_at

    def health_check(self) -> ProviderHealth:
        try:
            stores = csv_repository.list_stores(self._data_dir)
            ok = bool(stores)
            return ProviderHealth(
                ok=ok,
                status="healthy" if ok else "degraded",
                provider_name=self.provider_name,
                source=self.source_label,
                message=(
                    f"Inventory Data Source — {self.source_label} "
                    f"({len(stores)} stores)."
                    if ok
                    else f"Inventory Data Source — {self.source_label} has no stores."
                ),
                details={"store_count": len(stores), "real_pos": False},
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                ok=False,
                status="unavailable",
                provider_name=self.provider_name,
                source=self.source_label,
                message=f"Inventory provider unavailable: {exc}",
                details={"real_pos": False},
            )

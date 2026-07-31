"""Inventory position service."""

from __future__ import annotations

from models.inventory import InventoryPosition
from repositories import csv_repository


def get_inventory_position(store_id: str, sku: str) -> InventoryPosition:
    position = csv_repository.get_inventory_position(store_id, sku)
    if position is None:
        raise ValueError(f"No inventory for store={store_id} sku={sku}")
    return position

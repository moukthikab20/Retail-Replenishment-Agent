"""Inventory position service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import AS_OF_DATE, INVENTORY_STALE_DAYS
from models.inventory import InventoryPosition
from repositories import csv_repository


def get_inventory_position(store_id: str, sku: str) -> InventoryPosition:
    position = csv_repository.get_inventory_position(store_id, sku)
    if position is None:
        raise ValueError(f"No inventory for store={store_id} sku={sku}")
    return position


def is_inventory_stale(
    position: InventoryPosition,
    *,
    as_of: str | None = None,
    stale_days: int | None = None,
) -> bool:
    """True when inventory updated_at is older than the allowed age vs as-of date."""
    limit = INVENTORY_STALE_DAYS if stale_days is None else stale_days
    ref = datetime.fromisoformat(as_of or AS_OF_DATE)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    updated = position.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age_days = (ref - updated).total_seconds() / 86400.0
    return age_days > limit


def get_open_orders(store_id: str, sku: str) -> dict[str, Any]:
    """
    Return open inbound quantity for a store/SKU.

    Demo data has no separate open-PO feed; inbound open quantity is the
    inventory in_transit field. No replenishment formula changes.
    """
    position = get_inventory_position(store_id, sku)
    qty = int(position.in_transit)
    open_orders: list[dict[str, Any]] = []
    if qty > 0:
        open_orders.append(
            {
                "order_type": "in_transit",
                "quantity": qty,
                "store_id": store_id,
                "sku": sku,
            }
        )
    return {
        "store_id": store_id,
        "sku": sku,
        "open_order_quantity": qty,
        "open_orders": open_orders,
        "status": "ok",
    }

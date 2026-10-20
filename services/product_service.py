"""Product master service."""

from __future__ import annotations

from typing import Any

from integrations.factory import get_product_provider
from models.product import Product


def get_product_details(sku: str) -> Product:
    record = get_product_provider().get_product(sku)
    if record is None:
        raise ValueError(f"Unknown SKU: {sku}")
    return record.to_product()


def get_product_record(sku: str) -> dict[str, Any]:
    record = get_product_provider().get_product(sku)
    if record is None:
        raise ValueError(f"Unknown SKU: {sku}")
    return record.model_dump(mode="json")


def list_store_skus(store_id: str) -> list[str]:
    return get_product_provider().list_skus_for_store(store_id)


def list_stores() -> list[dict[str, str]]:
    return get_product_provider().list_stores()


def store_name_map() -> dict[str, str]:
    """Store id → display name from inventory master (single source of truth)."""
    return {
        str(row["store_id"]): str(row["store_name"])
        for row in list_stores()
        if row.get("store_id") and row.get("store_name")
    }


def store_display_name(store_id: str | None) -> str:
    """User-facing store label — never returns a bare code when master data exists."""
    if not store_id:
        return "—"
    sid = str(store_id).strip()
    if not sid or sid == "—":
        return "—"
    return store_name_map().get(sid, sid)


def store_id_for_display_name(store_name: str | None) -> str | None:
    """Resolve a display name back to store id for filtering (ids unchanged in logic)."""
    if not store_name:
        return None
    target = str(store_name).strip()
    for row in list_stores():
        if str(row.get("store_name")) == target:
            return str(row["store_id"])
    return None

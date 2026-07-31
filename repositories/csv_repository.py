"""CSV-backed read repository for products, inventory, and sales."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config import (
    DATA_DIR,
    DEFAULT_MAXIMUM_ORDER_QUANTITY,
    DEFAULT_MINIMUM_ORDER_QUANTITY,
    DEFAULT_RESERVED_UNITS,
    DEFAULT_UNIT_COST,
)
from models.inventory import InventoryPosition
from models.product import Product


@lru_cache(maxsize=1)
def _load_frames(data_dir: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = Path(data_dir)
    products = pd.read_csv(root / "products.csv")
    inventory = pd.read_csv(root / "inventory.csv")
    sales = pd.read_csv(root / "sales.csv")
    sales["date"] = pd.to_datetime(sales["date"])
    return products, inventory, sales


def clear_csv_cache() -> None:
    _load_frames.cache_clear()


def get_frames(data_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return _load_frames(str(data_dir or DATA_DIR))


def list_stores(data_dir: Path | None = None) -> list[dict[str, str]]:
    _, inventory, _ = get_frames(data_dir)
    stores = inventory[["store_id", "store_name"]].drop_duplicates().sort_values("store_id")
    return [
        {"store_id": row.store_id, "store_name": row.store_name}
        for row in stores.itertuples(index=False)
    ]


def list_skus_for_store(store_id: str, data_dir: Path | None = None) -> list[str]:
    _, inventory, _ = get_frames(data_dir)
    return (
        inventory.loc[inventory["store_id"] == store_id, "sku"].drop_duplicates().sort_values().tolist()
    )


def get_product(sku: str, data_dir: Path | None = None) -> Product | None:
    products, _, _ = get_frames(data_dir)
    rows = products.loc[products["sku"] == sku]
    if rows.empty:
        return None
    row = rows.iloc[0]
    case_pack = int(row["case_pack_size"])
    min_qty = int(row["minimum_order_quantity"]) if "minimum_order_quantity" in row.index else DEFAULT_MINIMUM_ORDER_QUANTITY
    max_qty = (
        int(row["maximum_order_quantity"])
        if "maximum_order_quantity" in row.index
        else DEFAULT_MAXIMUM_ORDER_QUANTITY
    )
    unit_cost = row["unit_cost"] if "unit_cost" in row.index else DEFAULT_UNIT_COST
    return Product(
        sku=str(row["sku"]),
        product_name=str(row["product_name"]),
        unit_cost=unit_cost,
        case_pack=case_pack if case_pack > 0 else 1,
        minimum_order_quantity=max(0, min_qty),
        maximum_order_quantity=max(case_pack, max_qty),
        safety_stock_units=int(row["safety_stock_units"]),
    )


def get_inventory_position(
    store_id: str,
    sku: str,
    data_dir: Path | None = None,
) -> InventoryPosition | None:
    products, inventory, _ = get_frames(data_dir)
    inv_rows = inventory.loc[(inventory["store_id"] == store_id) & (inventory["sku"] == sku)]
    if inv_rows.empty:
        return None
    inv = inv_rows.iloc[0]
    product = get_product(sku, data_dir)
    safety = product.safety_stock_units if product else 0
    reserved = int(inv["reserved"]) if "reserved" in inv.index else DEFAULT_RESERVED_UNITS
    updated_at = datetime.now(timezone.utc)
    if "updated_at" in inv.index and pd.notna(inv["updated_at"]):
        updated_at = pd.to_datetime(inv["updated_at"]).to_pydatetime()
    return InventoryPosition(
        store_id=store_id,
        sku=sku,
        on_hand=int(inv["on_hand"]),
        reserved=max(0, reserved),
        in_transit=int(inv["in_transit"]),
        safety_stock=safety,
        updated_at=updated_at,
        store_name=str(inv["store_name"]) if "store_name" in inv.index else None,
    )


def get_sales_frame(data_dir: Path | None = None) -> pd.DataFrame:
    _, _, sales = get_frames(data_dir)
    return sales.copy()

"""Product master service."""

from __future__ import annotations

from models.product import Product
from repositories import csv_repository


def get_product_details(sku: str) -> Product:
    product = csv_repository.get_product(sku)
    if product is None:
        raise ValueError(f"Unknown SKU: {sku}")
    return product


def list_store_skus(store_id: str) -> list[str]:
    return csv_repository.list_skus_for_store(store_id)


def list_stores() -> list[dict[str, str]]:
    return csv_repository.list_stores()

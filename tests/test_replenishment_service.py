"""Replenishment service tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from models.inventory import InventoryPosition
from models.product import Product
from services.replenishment_service import calculate_replenishment


def _product(**kwargs) -> Product:
    base = dict(
        sku="SKU-1",
        product_name="Test",
        unit_cost=Decimal("1.00"),
        case_pack=6,
        minimum_order_quantity=0,
        maximum_order_quantity=9999,
        safety_stock_units=12,
    )
    base.update(kwargs)
    return Product(**base)


def _inv(**kwargs) -> InventoryPosition:
    base = dict(
        store_id="ST001",
        sku="SKU-1",
        on_hand=10,
        reserved=0,
        in_transit=2,
        safety_stock=12,
        updated_at=datetime.now(timezone.utc),
    )
    base.update(kwargs)
    return InventoryPosition(**base)


def test_normal_calculation():
    result = calculate_replenishment(
        store_id="ST001",
        sku="SKU-1",
        forecast_units=Decimal("20"),
        inventory=_inv(on_hand=10, reserved=0, in_transit=2, safety_stock=12),
        product=_product(case_pack=6),
    )
    # raw = 20 + 12 - 10 - 2 = 20 → case pack 24
    assert result.raw_quantity == Decimal("20.00")
    assert result.recommended_quantity == 24


def test_negative_raw_becomes_zero():
    result = calculate_replenishment(
        store_id="ST001",
        sku="SKU-1",
        forecast_units=Decimal("5"),
        inventory=_inv(on_hand=100, in_transit=0, safety_stock=0),
        product=_product(case_pack=6),
    )
    assert result.recommended_quantity == 0
    assert "floored_at_zero" in result.constraints_applied


def test_case_pack_rounding():
    result = calculate_replenishment(
        store_id="ST001",
        sku="SKU-1",
        forecast_units=Decimal("10"),
        inventory=_inv(on_hand=0, in_transit=0, safety_stock=1),
        product=_product(case_pack=8),
    )
    # raw=11 → ceil to 16
    assert result.recommended_quantity == 16


def test_minimum_quantity():
    result = calculate_replenishment(
        store_id="ST001",
        sku="SKU-1",
        forecast_units=Decimal("1"),
        inventory=_inv(on_hand=0, in_transit=0, safety_stock=0),
        product=_product(case_pack=1, minimum_order_quantity=10, maximum_order_quantity=100),
    )
    assert result.recommended_quantity == 10
    assert "minimum_order_quantity" in result.constraints_applied


def test_maximum_quantity():
    result = calculate_replenishment(
        store_id="ST001",
        sku="SKU-1",
        forecast_units=Decimal("500"),
        inventory=_inv(on_hand=0, in_transit=0, safety_stock=0),
        product=_product(case_pack=10, minimum_order_quantity=0, maximum_order_quantity=50),
    )
    assert result.recommended_quantity == 50
    assert "maximum_order_quantity" in result.constraints_applied


def test_shelf_capacity_restriction():
    result = calculate_replenishment(
        store_id="ST001",
        sku="SKU-1",
        forecast_units=Decimal("100"),
        inventory=_inv(on_hand=10, reserved=0, in_transit=2, safety_stock=12),
        product=_product(case_pack=6, shelf_capacity=30),
    )
    # Without shelf: raw=100+12-10-2=100 → case pack 102.
    # Room on shelf: 30 - 10 - 2 = 18 → largest case-pack multiple = 18.
    assert result.recommended_quantity == 18
    assert "shelf_capacity" in result.constraints_applied

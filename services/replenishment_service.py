"""Deterministic replenishment arithmetic."""

from __future__ import annotations

import math
from decimal import Decimal

from models.inventory import InventoryPosition
from models.product import Product
from models.replenishment import ReplenishmentResult


def calculate_replenishment(
    *,
    store_id: str,
    sku: str,
    forecast_units: Decimal | float,
    inventory: InventoryPosition,
    product: Product,
) -> ReplenishmentResult:
    """
    raw_quantity = forecast_units + safety_stock - usable_on_hand - in_transit
    Then apply non-negative floor, MOQ, case-pack rounding, and maximum.
    """
    forecast = Decimal(str(forecast_units))
    usable = inventory.usable_on_hand
    safety = inventory.safety_stock
    in_transit = inventory.in_transit
    case_pack = product.case_pack if product.case_pack > 0 else 1

    raw = forecast + Decimal(safety) - Decimal(usable) - Decimal(in_transit)
    constraints: list[str] = []
    quantity = max(Decimal("0"), raw)
    if raw < 0:
        constraints.append("floored_at_zero")

    qty_int = int(math.ceil(float(quantity))) if quantity > 0 else 0

    if qty_int > 0 and qty_int < product.minimum_order_quantity:
        qty_int = product.minimum_order_quantity
        constraints.append("minimum_order_quantity")

    before_round = qty_int
    if qty_int > 0:
        qty_int = int(math.ceil(qty_int / case_pack) * case_pack)
        if qty_int != before_round:
            constraints.append("case_pack_rounding")

    if qty_int > product.maximum_order_quantity:
        # Round down to largest valid case-pack multiple at or below max
        max_packs = product.maximum_order_quantity // case_pack
        qty_int = max_packs * case_pack
        constraints.append("maximum_order_quantity")

    shelf_cap = product.shelf_capacity
    if shelf_cap is not None and qty_int > 0:
        room = int(shelf_cap) - int(usable) - int(in_transit)
        if room <= 0:
            qty_int = 0
            constraints.append("shelf_capacity")
        elif qty_int > room:
            max_packs = room // case_pack
            qty_int = max_packs * case_pack
            constraints.append("shelf_capacity")

    rounding_adjustment = qty_int - int(math.floor(float(max(Decimal("0"), raw))))
    days_of_supply = _days_of_supply(usable + in_transit, forecast)

    return ReplenishmentResult(
        store_id=store_id,
        sku=sku,
        raw_quantity=raw.quantize(Decimal("0.01")),
        recommended_quantity=qty_int,
        case_pack=case_pack,
        rounding_adjustment=rounding_adjustment,
        constraints_applied=constraints,
        usable_on_hand=usable,
        in_transit=in_transit,
        safety_stock=safety,
        forecast_units=forecast.quantize(Decimal("0.01")),
        days_of_supply=days_of_supply,
        details={
            "on_hand": inventory.on_hand,
            "reserved": inventory.reserved,
            "minimum_order_quantity": product.minimum_order_quantity,
            "maximum_order_quantity": product.maximum_order_quantity,
            "shelf_capacity": shelf_cap,
        },
    )


def nearest_case_pack_quantities(quantity: int, case_pack: int) -> tuple[int | None, int | None]:
    if case_pack <= 0:
        case_pack = 1
    if quantity <= 0:
        return 0, case_pack
    lower = (quantity // case_pack) * case_pack
    higher = lower if quantity % case_pack == 0 else lower + case_pack
    if quantity % case_pack == 0:
        return max(0, quantity - case_pack), quantity + case_pack
    return lower, higher


def _days_of_supply(available: int, forecast_units: Decimal) -> Decimal | None:
    if forecast_units <= 0:
        return None
    daily = forecast_units / Decimal("7")
    if daily <= 0:
        return None
    return (Decimal(available) / daily).quantize(Decimal("0.1"))

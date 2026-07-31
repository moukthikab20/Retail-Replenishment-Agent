"""Basic replenishment calculation for the POC."""

from __future__ import annotations

import math
from typing import Any


def calculate_replenishment(
    total_forecast: float,
    safety_stock: float,
    on_hand: float,
    in_transit: float,
    case_pack_size: int,
) -> dict[str, Any]:
    """
    Reorder qty = forecast + safety stock - on hand - in transit.
    Floor at zero, then round up to case pack size.
    """
    raw_reorder = total_forecast + safety_stock - on_hand - in_transit
    non_negative = max(0.0, raw_reorder)

    if case_pack_size <= 0:
        case_pack_size = 1

    if non_negative == 0:
        rounded_reorder = 0
    else:
        rounded_reorder = int(math.ceil(non_negative / case_pack_size) * case_pack_size)

    days_of_supply = (
        (on_hand + in_transit) / (total_forecast / 7)
        if total_forecast > 0
        else float("inf")
    )

    return {
        "raw_reorder": round(raw_reorder, 2),
        "recommended_order_qty": rounded_reorder,
        "case_pack_size": case_pack_size,
        "safety_stock": safety_stock,
        "on_hand": on_hand,
        "in_transit": in_transit,
        "available_inventory": on_hand + in_transit,
        "days_of_supply": round(days_of_supply, 1) if days_of_supply != float("inf") else None,
        "projected_position_after_order": on_hand + in_transit + rounded_reorder,
    }


def assess_inventory_risk(
    days_of_supply: float | None,
    recommended_order_qty: int,
    total_forecast: float,
    on_hand: float,
) -> str:
    """Simple heuristic for stockout vs overstock vs balanced."""
    if total_forecast <= 0 and on_hand > 0:
        return "overstock"

    if days_of_supply is None:
        return "balanced"

    if days_of_supply < 3 or (recommended_order_qty > 0 and on_hand < total_forecast * 0.3):
        return "stockout"
    if days_of_supply > 14 and recommended_order_qty == 0:
        return "overstock"
    return "balanced"

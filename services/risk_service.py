"""Deterministic replenishment risk assessment."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from config import (
    RISK_ON_HAND_FORECAST_RATIO,
    RISK_OVERSTOCK_DOS_THRESHOLD,
    RISK_STOCKOUT_DOS_THRESHOLD,
)


def assess_replenishment_risk(
    *,
    days_of_supply: Decimal | float | None,
    recommended_quantity: int,
    forecast_units: Decimal | float,
    on_hand: int,
    usable_on_hand: int | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """
    Return risk level, reasons, and projected days of supply.

    Levels: stockout | overstock | balanced | manual_review | insufficient_data
    """
    forecast = Decimal(str(forecast_units))
    dos = None if days_of_supply is None else Decimal(str(days_of_supply))
    oh = usable_on_hand if usable_on_hand is not None else on_hand
    reasons: list[str] = []

    if method == "insufficient_data_zero" and forecast <= 0 and oh == 0:
        return {
            "risk_level": "insufficient_data",
            "reasons": ["No sales history and zero on-hand inventory"],
            "projected_days_of_supply": None,
        }

    if forecast <= 0 and oh > 0:
        reasons.append("Zero/negative forecast with positive on-hand")
        return {
            "risk_level": "overstock",
            "reasons": reasons,
            "projected_days_of_supply": None,
        }

    if dos is None and forecast <= 0:
        return {
            "risk_level": "balanced",
            "reasons": ["Days of supply undefined with zero forecast"],
            "projected_days_of_supply": None,
        }

    if dos is not None and dos < Decimal(str(RISK_STOCKOUT_DOS_THRESHOLD)):
        reasons.append(f"Days of supply {dos} below {RISK_STOCKOUT_DOS_THRESHOLD}")
    if recommended_quantity > 0 and oh < float(forecast) * RISK_ON_HAND_FORECAST_RATIO:
        reasons.append("On-hand below 30% of forecast with positive reorder")

    if reasons:
        return {
            "risk_level": "stockout",
            "reasons": reasons,
            "projected_days_of_supply": float(dos) if dos is not None else None,
        }

    if (
        dos is not None
        and dos > Decimal(str(RISK_OVERSTOCK_DOS_THRESHOLD))
        and recommended_quantity == 0
    ):
        return {
            "risk_level": "overstock",
            "reasons": [f"Days of supply {dos} above {RISK_OVERSTOCK_DOS_THRESHOLD} with zero reorder"],
            "projected_days_of_supply": float(dos),
        }

    # Large reorder with unclear coverage may need manual review
    if recommended_quantity > 0 and dos is not None and dos > Decimal("21"):
        return {
            "risk_level": "manual_review",
            "reasons": ["High days of supply with non-zero recommended order"],
            "projected_days_of_supply": float(dos),
        }

    return {
        "risk_level": "balanced",
        "reasons": ["Inventory position within configured thresholds"],
        "projected_days_of_supply": float(dos) if dos is not None else None,
    }


def project_risk_after_order(
    *,
    usable_on_hand: int,
    in_transit: int,
    order_quantity: int,
    forecast_units: Decimal | float,
) -> dict[str, Any]:
    forecast = Decimal(str(forecast_units))
    available = usable_on_hand + in_transit + order_quantity
    if forecast <= 0:
        dos = None
    else:
        daily = forecast / Decimal("7")
        dos = (Decimal(available) / daily).quantize(Decimal("0.1")) if daily > 0 else None

    return assess_replenishment_risk(
        days_of_supply=dos,
        recommended_quantity=0 if order_quantity > 0 else 0,
        forecast_units=forecast,
        on_hand=available,
        usable_on_hand=available,
    )

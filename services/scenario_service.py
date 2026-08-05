"""Deterministic what-if scenarios for follow-up questions.

These helpers never mutate the stored recommendation. Impact is computed from
saved recommendation fields plus existing risk/replenishment/product policy
services — formulas are not duplicated in the agent tool layer.
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, TypedDict

from config import ESCALATION_REQUIRED_PERCENT, ESCALATION_WARNING_PERCENT
from services import (
    inventory_service,
    product_service,
    recommendation_service,
    risk_service,
)
from services.errors import AppError
from services.replenishment_service import nearest_case_pack_quantities


class QuantityScenarioResult(TypedDict, total=False):
    status: str
    scenario_type: str
    hypothetical: bool
    recommendation_id: str
    agent_recommended_quantity: int
    proposed_quantity: int
    difference_units: int
    difference_percent: float
    projected_inventory: int
    projected_days_of_supply: float | None
    projected_risk: str
    case_pack_compliant: bool
    nearest_lower_valid_quantity: int | None
    nearest_higher_valid_quantity: int | None
    minimum_order_compliant: bool
    maximum_order_compliant: bool
    requires_warning: bool
    requires_escalation: bool
    warning_messages: list[str]
    summary: str
    verified_facts: list[str]
    assumptions: list[str]


def evaluate_quantity_scenario(
    recommendation_id: str,
    proposed_quantity: int,
) -> QuantityScenarioResult:
    """
    Hypothetical alternate order quantity vs the saved recommendation.

    Does not persist a human review, change the recommendation, or round the
    proposed quantity to case pack.
    """
    if isinstance(proposed_quantity, bool) or not isinstance(proposed_quantity, int):
        raise AppError("proposed_quantity must be a whole number", code="domain_error")
    if proposed_quantity < 0:
        raise AppError("proposed_quantity must be >= 0", code="domain_error")

    rec = recommendation_service.get_recommendation(recommendation_id)
    agent_qty = int(rec["agent_recommended_quantity"])
    store_id = str(rec["store_id"])
    sku = str(rec["sku"])
    product = product_service.get_product_details(sku)
    case_pack = int(product.case_pack)
    forecast_units = float(rec.get("forecast_units") or 0)

    inventory = inventory_service.get_inventory_position(store_id, sku)
    usable = int(inventory.usable_on_hand)
    in_transit = int(inventory.in_transit)

    lower, higher = nearest_case_pack_quantities(proposed_quantity, case_pack)
    case_pack_compliant = proposed_quantity == 0 or proposed_quantity % case_pack == 0
    minimum_order_compliant = not (
        proposed_quantity > 0 and proposed_quantity < product.minimum_order_quantity
    )
    maximum_order_compliant = proposed_quantity <= product.maximum_order_quantity

    difference_units = proposed_quantity - agent_qty
    if agent_qty == 0:
        difference_percent = 100.0 if proposed_quantity != 0 else 0.0
    else:
        difference_percent = float(
            (
                (Decimal(abs(difference_units)) / Decimal(agent_qty)) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

    projected_inventory = usable + in_transit + proposed_quantity
    projected = risk_service.project_risk_after_order(
        usable_on_hand=usable,
        in_transit=in_transit,
        order_quantity=proposed_quantity,
        forecast_units=forecast_units,
    )
    projected_risk = str(projected["risk_level"])
    projected_dos = projected.get("projected_days_of_supply")
    if projected_dos is not None:
        projected_dos = float(projected_dos)

    warning_messages: list[str] = []
    if not case_pack_compliant:
        warning_messages.append(
            f"Quantity {proposed_quantity} is not a multiple of case pack {case_pack}. "
            f"Nearest valid: lower={lower}, higher={higher}. "
            "Proposed quantity was not rounded."
        )
    if not minimum_order_compliant:
        warning_messages.append(
            f"Quantity {proposed_quantity} is below minimum order quantity "
            f"{product.minimum_order_quantity}."
        )
    if not maximum_order_compliant:
        warning_messages.append(
            f"Quantity {proposed_quantity} exceeds maximum order quantity "
            f"{product.maximum_order_quantity}."
        )

    requires_escalation = False
    if proposed_quantity == 0:
        requires_escalation = True
        warning_messages.append("Zero quantity requires higher approval if submitted as a review.")
    elif Decimal(str(difference_percent)) > ESCALATION_REQUIRED_PERCENT:
        requires_escalation = True
        warning_messages.append(
            f"Change of {difference_percent}% exceeds {ESCALATION_REQUIRED_PERCENT}% "
            "escalation threshold."
        )
    elif Decimal(str(difference_percent)) > ESCALATION_WARNING_PERCENT:
        warning_messages.append(
            f"Change of {difference_percent}% exceeds {ESCALATION_WARNING_PERCENT}% "
            "warning threshold."
        )

    requires_warning = bool(warning_messages) or (
        Decimal(str(difference_percent)) > ESCALATION_WARNING_PERCENT
    )

    if proposed_quantity == agent_qty:
        impact = "Proposed quantity matches the saved agent recommendation."
    elif proposed_quantity == 0:
        impact = (
            "Ordering zero units leaves cover unchanged versus placing the recommended order."
        )
    elif difference_units < 0:
        impact = (
            f"Ordering {proposed_quantity} units is {abs(difference_units)} below the saved "
            f"recommendation of {agent_qty}."
        )
    else:
        impact = (
            f"Ordering {proposed_quantity} units is {difference_units} above the saved "
            f"recommendation of {agent_qty}."
        )

    facts = [
        f"recommendation_id={recommendation_id}",
        f"agent_recommended_quantity={agent_qty}",
        f"proposed_quantity={proposed_quantity}",
        f"difference_units={difference_units}",
        f"difference_percent={difference_percent}",
        f"projected_inventory={projected_inventory}",
        f"projected_days_of_supply={projected_dos}",
        f"projected_risk={projected_risk}",
        f"case_pack={case_pack}",
        f"case_pack_compliant={case_pack_compliant}",
        f"minimum_order_compliant={minimum_order_compliant}",
        f"maximum_order_compliant={maximum_order_compliant}",
        f"requires_warning={requires_warning}",
        f"requires_escalation={requires_escalation}",
        f"forecast_units={forecast_units}",
        f"usable_on_hand={usable}",
        f"in_transit={in_transit}",
    ]
    assumptions = [
        "Hypothetical quantity scenario only; the stored recommendation was not changed.",
        "No human review, approval, or purchase order was created.",
        "Projected inventory assumes usable on-hand + in-transit + proposed quantity.",
        "Case-pack and order-limit checks report compliance without silently rounding.",
    ]

    return {
        "status": "ok",
        "scenario_type": "quantity",
        "hypothetical": True,
        "recommendation_id": recommendation_id,
        "agent_recommended_quantity": agent_qty,
        "proposed_quantity": proposed_quantity,
        "difference_units": difference_units,
        "difference_percent": difference_percent,
        "projected_inventory": projected_inventory,
        "projected_days_of_supply": projected_dos,
        "projected_risk": projected_risk,
        "case_pack": case_pack,
        "case_pack_compliant": case_pack_compliant,
        "nearest_lower_valid_quantity": lower,
        "nearest_higher_valid_quantity": higher,
        "minimum_order_quantity": int(product.minimum_order_quantity),
        "maximum_order_quantity": int(product.maximum_order_quantity),
        "minimum_order_compliant": minimum_order_compliant,
        "maximum_order_compliant": maximum_order_compliant,
        "requires_warning": requires_warning,
        "requires_escalation": requires_escalation,
        "warning_messages": warning_messages,
        # Backward-compatible aliases used by existing follow-up paths/tests.
        "quantity_delta": difference_units,
        "proposed_aligned_to_case_pack": case_pack_compliant,
        "nearest_case_pack_down": lower,
        "nearest_case_pack_up": higher,
        "scenario_risk": {
            "risk_level": projected_risk,
            "projected_days_of_supply": projected_dos,
            "reasons": list(projected.get("reasons") or []),
        },
        "order_still_needed": proposed_quantity > 0 or agent_qty > 0,
        "summary": impact,
        "verified_facts": facts,
        "assumptions": assumptions,
    }


class DelayScenarioResult(TypedDict, total=False):
    status: str
    scenario_type: str
    hypothetical: bool
    recommendation_id: str
    delay_days: int
    original_days_of_supply: float | None
    revised_days_of_supply: float | None
    original_risk: str
    revised_risk: str
    expected_shortfall_units: float
    stockout_before_arrival: bool
    additional_quantity_suggested: int
    warning_messages: list[str]
    summary: str
    verified_facts: list[str]
    assumptions: list[str]


def evaluate_delay_scenario(
    recommendation_id: str,
    delay_days: int,
) -> DelayScenarioResult:
    """
    Hypothetical inbound shipment delay impact.

    Uses stored forecast/inventory facts only. Does not change the recommendation
    or create a review, approval, or purchase order.
    """
    if isinstance(delay_days, bool) or not isinstance(delay_days, int):
        raise AppError("delay_days must be an integer", code="domain_error")
    if delay_days < 0:
        raise AppError("delay_days must be >= 0", code="domain_error")

    rec = recommendation_service.get_recommendation(recommendation_id)
    agent_qty = int(rec["agent_recommended_quantity"])
    usable = int(rec.get("usable_on_hand") or 0)
    in_transit = int(rec.get("in_transit") or 0)
    forecast_units = float(rec.get("forecast_units") or 0)
    original_dos = rec.get("days_of_supply")
    if original_dos is not None:
        original_dos = float(original_dos)
    original_risk = str(rec.get("risk_level") or "manual_review")

    avg_daily = float(rec.get("average_daily_sales") or 0)
    if avg_daily <= 0 and forecast_units > 0:
        avg_daily = forecast_units / 7.0

    warning_messages: list[str] = []
    missing_forecast = avg_daily <= 0 or forecast_units <= 0
    if missing_forecast:
        warning_messages.append(
            "Forecast/average daily sales is missing or zero on the saved recommendation; "
            "delay impact cannot be fully projected."
        )

    if missing_forecast:
        demand_during_delay = 0.0
        projected_on_hand_at_arrival = float(usable)
        revised_dos: float | None = None
        expected_shortfall = 0.0
        stockout_before_arrival = False
        additional_quantity_suggested = 0
    else:
        demand_during_delay = avg_daily * delay_days
        projected_on_hand_at_arrival = usable - demand_during_delay
        # Days of supply remaining from usable stock at the delayed arrival point.
        revised_dos = round(max(0.0, projected_on_hand_at_arrival) / avg_daily, 1)
        expected_shortfall = max(0.0, -projected_on_hand_at_arrival)
        stockout_before_arrival = projected_on_hand_at_arrival < 0
        additional_quantity_suggested = (
            int(math.ceil(expected_shortfall)) if expected_shortfall > 0 else 0
        )

    risk = risk_service.assess_replenishment_risk(
        days_of_supply=revised_dos,
        recommended_quantity=agent_qty,
        forecast_units=forecast_units,
        on_hand=max(0, int(round(projected_on_hand_at_arrival))),
        usable_on_hand=max(0, int(round(projected_on_hand_at_arrival))),
    )
    revised_risk = str(risk["risk_level"])

    if in_transit <= 0 and delay_days > 0:
        warning_messages.append(
            "Saved in_transit/open inbound quantity is zero; delay impact on inbound "
            "arrival is limited."
        )
    if stockout_before_arrival:
        warning_messages.append(
            f"Projected stockout before arrival of about {expected_shortfall:.1f} units."
        )
    if additional_quantity_suggested > 0:
        warning_messages.append(
            f"Hypothetical additional quantity suggested to cover shortfall: "
            f"{additional_quantity_suggested}."
        )

    if delay_days == 0:
        summary = "No delay assumed; inbound timing matches the saved recommendation."
    elif missing_forecast:
        summary = (
            f"Hypothetical {delay_days}-day delay cannot be fully quantified because "
            "forecast data is missing on the saved recommendation."
        )
    elif in_transit <= 0:
        summary = (
            f"A {delay_days}-day delay has limited inbound impact because open/in-transit "
            "quantity is currently zero on the saved recommendation."
        )
    elif stockout_before_arrival:
        summary = (
            f"If the {in_transit}-unit inbound shipment is delayed by {delay_days} days, "
            f"usable stock is projected to fall short by about {expected_shortfall:.1f} units "
            "before arrival."
        )
    else:
        summary = (
            f"If the {in_transit}-unit inbound shipment is delayed by {delay_days} days, "
            f"about {projected_on_hand_at_arrival:.1f} usable units would remain at arrival "
            "under the saved average daily sales."
        )

    facts = [
        f"recommendation_id={recommendation_id}",
        f"delay_days={delay_days}",
        f"original_days_of_supply={original_dos}",
        f"revised_days_of_supply={revised_dos}",
        f"original_risk={original_risk}",
        f"revised_risk={revised_risk}",
        f"expected_shortfall_units={expected_shortfall}",
        f"stockout_before_arrival={stockout_before_arrival}",
        f"additional_quantity_suggested={additional_quantity_suggested}",
        f"in_transit={in_transit}",
        f"usable_on_hand={usable}",
        f"average_daily_sales={avg_daily}",
        f"demand_during_delay={demand_during_delay}",
        f"projected_on_hand_at_arrival={projected_on_hand_at_arrival}",
        f"agent_recommended_quantity={agent_qty}",
    ]
    assumptions = [
        "Hypothetical delay scenario only; the stored recommendation was not changed.",
        "No human review, approval, or purchase order was created.",
        "Demand during the delay uses average daily sales from the saved recommendation.",
        "Inbound open quantity is treated as the saved in_transit value.",
    ]

    return {
        "status": "ok",
        "scenario_type": "delay",
        "hypothetical": True,
        "recommendation_id": recommendation_id,
        "delay_days": delay_days,
        "original_days_of_supply": original_dos,
        "revised_days_of_supply": revised_dos,
        "original_risk": original_risk,
        "revised_risk": revised_risk,
        "expected_shortfall_units": float(expected_shortfall),
        "stockout_before_arrival": stockout_before_arrival,
        "additional_quantity_suggested": additional_quantity_suggested,
        "warning_messages": warning_messages,
        "in_transit": in_transit,
        "usable_on_hand": usable,
        "average_daily_sales": avg_daily,
        "demand_during_delay": demand_during_delay,
        "projected_on_hand_at_arrival": projected_on_hand_at_arrival,
        "cover_days_without_inbound": revised_dos,
        "shortfall_units": float(expected_shortfall),
        "agent_recommended_quantity": agent_qty,
        "scenario_risk": risk,
        "order_still_needed": agent_qty > 0 or expected_shortfall > 0,
        "summary": summary,
        "verified_facts": facts,
        "assumptions": assumptions,
    }

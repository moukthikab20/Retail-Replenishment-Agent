"""Orchestration agent: explains replenishment recommendation via OpenAI."""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


SYSTEM_PROMPT = """You are a retail replenishment analyst for Infolob Solutions.
Explain inventory risk and the recommended order in clear, concise business language.
Focus on stockout or overstock risk based on the provided metrics.
Do not recalculate numbers — all figures are pre-computed by Python.
Respond in 3–5 sentences, left-aligned prose (no bullet lists).
"""


def _fallback_explanation(context: dict[str, Any]) -> str:
    risk = context.get("risk_level", "balanced")
    sku = context.get("product_name", context.get("sku", "SKU"))
    qty = context.get("recommended_order_qty", 0)
    days = context.get("days_of_supply")
    forecast = context.get("total_forecast", 0)

    if risk == "stockout":
        return (
            f"{sku} shows elevated stockout risk. Trailing sales support a "
            f"{forecast}-unit seven-day forecast, and current on-hand plus in-transit "
            f"cover roughly {days} days of demand. The agent recommends ordering "
            f"{qty} units (case-pack adjusted) to restore target coverage and safety stock."
        )
    if risk == "overstock":
        return (
            f"{sku} appears adequately stocked relative to the {forecast}-unit forecast. "
            f"Days of supply near {days} suggest limited near-term stockout exposure, "
            f"and no replenishment is required at this time. Holding excess inventory "
            f"would increase carrying cost without matching observed demand."
        )
    return (
        f"{sku} is in a balanced position against a {forecast}-unit seven-day forecast. "
        f"Available inventory covers about {days} days of projected demand. "
        f"The recommended order of {qty} units aligns safety stock with expected sell-through "
        f"while avoiding unnecessary overstock."
    )


def generate_explanation(context: dict[str, Any]) -> str:
    """Call OpenAI for agent narrative; fall back to rule-based text if unavailable."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _fallback_explanation(context)

    client = OpenAI(api_key=api_key)
    user_content = (
        "Explain this replenishment scenario for a human approver:\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )

    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            max_tokens=280,
        )
        text = response.choices[0].message.content
        return text.strip() if text else _fallback_explanation(context)
    except Exception:
        return _fallback_explanation(context)


def build_agent_context(
    store_name: str,
    product_name: str,
    sku: str,
    forecast: dict[str, Any],
    replenishment: dict[str, Any],
    risk_level: str,
) -> dict[str, Any]:
    return {
        "store": store_name,
        "sku": sku,
        "product_name": product_name,
        "avg_daily_sales": forecast["avg_daily_sales"],
        "total_forecast": forecast["total_forecast"],
        "horizon_days": forecast["horizon_days"],
        "safety_stock": replenishment["safety_stock"],
        "on_hand": replenishment["on_hand"],
        "in_transit": replenishment["in_transit"],
        "recommended_order_qty": replenishment["recommended_order_qty"],
        "case_pack_size": replenishment["case_pack_size"],
        "days_of_supply": replenishment["days_of_supply"],
        "risk_level": risk_level,
    }

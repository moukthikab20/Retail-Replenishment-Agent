"""Business-facing catalog of replenishment policy / guardrail rules.

Maps internal PolicyConfig fields to display labels and explanations.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from models.policy import PolicyConfig

RuleFormatter = Callable[[PolicyConfig], str]


def _money(value: Decimal | float | int) -> str:
    return f"${Decimal(str(value)):,.2f}"


def _yes_no(flag: bool) -> str:
    return "Enabled" if flag else "Disabled"


def _exception_routing_value(policy: PolicyConfig) -> str:
    parts: list[str] = []
    parts.append(
        "Stockout → human review" if policy.require_review_for_stockout else "Stockout → no forced review"
    )
    parts.append(
        "Overstock → human review"
        if policy.require_review_for_overstock
        else "Overstock → no forced review"
    )
    return "; ".join(parts)


# Ordered for the Policy & Guardrails page (business-user vocabulary).
POLICY_RULE_CATALOG: list[dict[str, Any]] = [
    {
        "business_name": "Auto-release ceiling",
        "internal_key": "auto_release_max_value",
        "explanation": (
            "Orders at or under this value may release automatically if all other "
            "rules pass."
        ),
        "format": lambda p: _money(p.auto_release_max_value),
        "field": "auto_release_max_value",
        "input": "money",
    },
    {
        "business_name": "Minimum confidence",
        "internal_key": "minimum_confidence",
        "explanation": (
            "Recommendations below this confidence score are routed to human review "
            "instead of auto-release."
        ),
        "format": lambda p: f"{Decimal(str(p.minimum_confidence)):.2f}",
        "field": "minimum_confidence",
        "input": "decimal",
    },
    {
        "business_name": "Maximum inventory-feed age",
        "internal_key": "maximum_inventory_age_hours",
        "explanation": (
            "Inventory positions older than this many hours are treated as stale and "
            "block automatic ordering."
        ),
        "format": lambda p: f"{p.maximum_inventory_age_hours} hours",
        "field": "maximum_inventory_age_hours",
        "input": "int",
    },
    {
        "business_name": "Exception routing",
        "internal_key": "exception_routing",
        "explanation": (
            "Defines which risk exceptions (stockout, overstock) must go to human "
            "review instead of auto-release."
        ),
        "format": _exception_routing_value,
        "field": None,
        "input": "exception_routing",
        "fields": ["require_review_for_stockout", "require_review_for_overstock"],
    },
    {
        "business_name": "Maximum days of supply",
        "internal_key": "maximum_days_of_supply",
        "explanation": (
            "Projected days of supply above this threshold are treated as overstock "
            "risk and typically require review."
        ),
        "format": lambda p: f"{Decimal(str(p.maximum_days_of_supply)):.1f} days",
        "field": "maximum_days_of_supply",
        "input": "decimal",
    },
    {
        "business_name": "Minimum historical demand requirement",
        "internal_key": "minimum_history_days",
        "explanation": (
            "SKUs with fewer unique sales history days than this requirement cannot "
            "clear auto-release confidence gates."
        ),
        "format": lambda p: f"{p.minimum_history_days} days",
        "field": "minimum_history_days",
        "input": "int",
    },
    {
        "business_name": "Promotion overlap rule",
        "internal_key": "require_review_for_promotion_overlap",
        "explanation": (
            "When enabled, recommendations that overlap an active or upcoming "
            "promotion are routed to human review."
        ),
        "format": lambda p: _yes_no(p.require_review_for_promotion_overlap),
        "field": "require_review_for_promotion_overlap",
        "input": "bool",
    },
    {
        "business_name": "Manual override threshold",
        "internal_key": "maximum_override_percent",
        "explanation": (
            "Human quantity adjustments beyond this percent of the agent "
            "recommendation require elevated approval."
        ),
        "format": lambda p: f"{Decimal(str(p.maximum_override_percent)):.0f}%",
        "field": "maximum_override_percent",
        "input": "decimal",
    },
    {
        "business_name": "Formal approval threshold",
        "internal_key": "require_formal_approval_above_value",
        "explanation": (
            "Order values above this amount require formal approval before a "
            "purchase order can be created."
        ),
        "format": lambda p: _money(p.require_formal_approval_above_value),
        "field": "require_formal_approval_above_value",
        "input": "money",
    },
]


def rule_rows_for_policy(policy: PolicyConfig) -> list[dict[str, str]]:
    """Read model: business name, explanation, configured value, internal key."""
    rows: list[dict[str, str]] = []
    for rule in POLICY_RULE_CATALOG:
        formatter: RuleFormatter = rule["format"]
        rows.append(
            {
                "business_name": rule["business_name"],
                "explanation": rule["explanation"],
                "configured_value": formatter(policy),
                "internal_key": rule["internal_key"],
            }
        )
    return rows

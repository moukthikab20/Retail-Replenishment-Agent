"""Overview landing workspace — queue-density presentation model.

Composes existing queue / overview read models only. No scoring or policy logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from services import product_service


BANNED_LANDING_TERMS = (
    "operating normally",
    "already cleared",
    "thursday briefing",
    "friday briefing",
    "saturday briefing",
    "sunday briefing",
    "monday briefing",
    "tuesday briefing",
    "wednesday briefing",
    "what changed since",
    "what does the ai",
    "scheduled analysis",
    "manual analysis",
    "run analysis now",
    "refresh status",
    "skus scored",
    "scheduler",
)


def first_name(display_name: str | None, fallback: str = "there") -> str:
    raw = (display_name or "").strip()
    if not raw:
        return fallback
    return raw.split()[0]


def contextual_greeting(
    display_name: str | None,
    *,
    now: datetime | None = None,
) -> str:
    hour = (now or datetime.now()).hour
    if hour < 12:
        lead = "Good morning"
    elif hour < 18:
        lead = "Good afternoon"
    else:
        lead = "Good evening"
    return f"{lead}, {first_name(display_name)}."


def _fmt_demand(value: object) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
        if n.is_integer():
            return f"{int(n):,}"
        return f"{n:,.1f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_dos(value: object) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
        text = f"{n:.1f}".rstrip("0").rstrip(".")
        return f"{text}d"
    except (TypeError, ValueError):
        return str(value)


def _urgency_key(row: dict[str, Any]) -> tuple:
    """Sort: stockout → blocked → approval → low confidence → overstock/no-order."""
    risk = row.get("risk_level") or ""
    disp = row.get("disposition") or ""
    exception = str(row.get("exception") or "").lower()
    failed = row.get("failed_rules") or []
    conf = row.get("confidence")
    try:
        dos = float(row["days_of_supply"]) if row.get("days_of_supply") is not None else 999.0
    except (TypeError, ValueError):
        dos = 999.0

    if risk == "stockout" or "stockout" in exception or "stockout_review" in failed:
        return (0, dos)
    if disp == "blocked":
        return (1, 0.0)
    if disp == "human_review" and row.get("open_for_decision"):
        return (2, 0.0)
    try:
        if conf is not None and float(conf) < 0.75:
            return (3, 0.0)
    except (TypeError, ValueError):
        pass
    if risk == "overstock" or disp == "no_order" or "overstock" in exception:
        return (4, 0.0)
    return (5, 0.0)


def prioritize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Actionable priorities for the landing table (business urgency, not DB order)."""
    actionable = [
        r
        for r in rows
        if (r.get("disposition") == "human_review" and r.get("open_for_decision"))
        or r.get("disposition") == "blocked"
    ]
    return sorted(actionable, key=_urgency_key)


def _landing_row(row: dict[str, Any]) -> dict[str, Any]:
    why = row.get("why") or row.get("exception") or "Needs attention"
    return {
        "recommendation_id": row.get("recommendation_id"),
        "item": row.get("item") or row.get("product_name") or row.get("sku") or "—",
        "store": row.get("store_name")
        or product_service.store_display_name(row.get("store_id")),
        "why": why,
        "demand_7d": row.get("forecast_units"),
        "demand_7d_display": _fmt_demand(row.get("forecast_units")),
        "days_of_supply": row.get("days_of_supply"),
        "days_of_supply_display": _fmt_dos(row.get("days_of_supply")),
        "agent_recommendation": row.get("recommendation_display")
        or (
            f"Order {row.get('agent_quantity')}"
            if row.get("agent_quantity") is not None
            else "—"
        ),
        "risk_level": row.get("risk_level"),
        "risk_label": row.get("risk_label") or why,
        "priority": row.get("priority") or "Normal",
        "disposition": row.get("disposition"),
        "order_value_display": row.get("order_value_display"),
    }


def landing_row(row: dict[str, Any]) -> dict[str, Any]:
    """Public alias for overview table row shaping."""
    return _landing_row(row)


def build_kpi_cards(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Only include KPIs with meaningful (non-zero) signal."""
    needs = int(summary.get("needs_review") or 0)
    blocked = int(summary.get("blocked") or 0)
    auto = int(summary.get("auto_released") or 0)
    value = float(summary.get("order_value_awaiting_decision") or 0)
    value_display = summary.get("order_value_awaiting_decision_display") or "$0.00"
    open_decisions = needs + blocked

    cards: list[dict[str, Any]] = []
    if needs > 0:
        cards.append(
            {
                "label": "Needs your review",
                "value": needs,
                "sub": "Human decision required",
                "accent": True,
            }
        )
    if blocked > 0:
        cards.append(
            {
                "label": "Blocked",
                "value": blocked,
                "sub": "Agent could not proceed",
            }
        )
    if auto > 0:
        cards.append(
            {
                "label": "Handled automatically",
                "value": auto,
                "sub": "Within policy",
            }
        )
    if value > 0 and open_decisions > 0:
        cards.append(
            {
                "label": "Purchase value awaiting decision",
                "value": value_display,
                "sub": f"Across {open_decisions} open decision{'s' if open_decisions != 1 else ''}",
            }
        )
    return cards


def build_landing_workspace(
    overview: dict[str, Any],
    *,
    display_name: str | None = None,
    queue_rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Operational landing model for Overview.

    Modes:
    - healthy: no actionable review/blocked items (incl. first-run / no-run)
    - actionable: summary KPIs + prioritized decision rows
    """
    metrics = overview.get("metrics") or {}
    baseline = overview.get("baseline_context") or {}
    summary = {
        "needs_review": int(metrics.get("needs_review") or 0),
        "blocked": int(metrics.get("blocked") or 0),
        "auto_released": int(metrics.get("handled_automatically") or 0),
        "no_order": int(metrics.get("no_order") or 0),
        "order_value_awaiting_decision": float(
            metrics.get("order_value_awaiting_decision") or 0
        ),
        "order_value_awaiting_decision_display": metrics.get(
            "order_value_awaiting_decision_display"
        )
        or "$0.00",
    }

    rows_in = queue_rows
    if rows_in is None:
        # Prefer full queue rows if overview attached them; else attention subset.
        rows_in = overview.get("queue_rows") or overview.get("attention") or []

    prioritized = [_landing_row(r) for r in prioritize_rows(list(rows_in))]
    needs = summary["needs_review"]
    blocked = summary["blocked"]
    healthy = needs == 0 and blocked == 0

    stores = int(baseline.get("store_count") or 0)
    skus = int(baseline.get("sku_count") or 0)

    cards = [] if healthy else build_kpi_cards(summary)

    healthy_secondary = "No stockout risks · No blocked purchases · No supplier exceptions"
    if summary["auto_released"] or summary["no_order"]:
        healthy_secondary = (
            f"{summary['auto_released']} handled automatically · "
            f"{summary['no_order']} no order needed · "
            f"No items need your review"
        )

    return {
        "greeting": contextual_greeting(display_name, now=now),
        "first_name": first_name(display_name),
        "mode": "healthy" if healthy else "actionable",
        "kpi_cards": cards,
        "priority_rows": prioritized,
        "section_title": "Today's replenishment priorities",
        "show_review_cta": not healthy and bool(prioritized or needs),
        "review_cta_label": "Review decisions",
        "healthy": {
            "title": "All clear today",
            "body": "No products currently need your approval or intervention.",
            "monitor": (
                f"The agent is monitoring {stores} stores and {skus} active products."
            ),
            "secondary": healthy_secondary,
            "show_inventory_link": True,
        },
        "summary": summary,
        "stores_monitored": stores,
        "products_monitored": skus,
    }


# ---- Back-compat shims for older imports (tests migrating off Q&A brief) ----

def build_morning_brief(
    overview: dict[str, Any],
    *,
    display_name: str | None = None,
    actor_role: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Deprecated alias — returns landing workspace shaped for new Overview."""
    del actor_role  # RBAC unchanged; landing does not alter permissions
    return build_landing_workspace(overview, display_name=display_name, now=now)


def briefing_text_blob(brief: dict[str, Any]) -> str:
    chunks = [str(brief.get("greeting") or "")]
    if brief.get("mode") == "healthy":
        h = brief.get("healthy") or {}
        chunks.extend(
            [
                str(h.get("title") or ""),
                str(h.get("body") or ""),
                str(h.get("monitor") or ""),
                str(h.get("secondary") or ""),
            ]
        )
    for card in brief.get("kpi_cards") or []:
        chunks.append(str(card.get("label") or ""))
        chunks.append(str(card.get("value") or ""))
        chunks.append(str(card.get("sub") or ""))
    chunks.append(str(brief.get("section_title") or ""))
    for row in brief.get("priority_rows") or []:
        chunks.append(str(row.get("item") or ""))
        chunks.append(str(row.get("why") or ""))
    return "\n".join(chunks)

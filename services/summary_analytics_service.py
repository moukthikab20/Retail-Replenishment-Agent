"""Historical replenishment analytics for the Summary page.

Reads persisted recommendations, human reviews, order intents, sales CSV, and
inventory snapshots. Does not invent outcomes (stockout days, fill rate, etc.).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select

from config import AS_OF_DATE
from database.connection import get_session, init_db
from database.models import HumanReviewRow, OrderIntentRow, RecommendationRow
from integrations.factory import get_inventory_provider, get_product_provider
from repositories import csv_repository
from services import product_service

UNAVAILABLE = "Not enough historical data for this metric."
OUTCOME_UNAVAILABLE = "Not enough historical outcome data."
NOT_ENOUGH_DATA_SUB = "Not enough historical data"
POST_ORDER_WINDOW_DAYS = 7
EXCESS_COVER_DAYS = 14.0

DECISION_TYPES = (
    ("all", "All decisions"),
    ("agent_approved", "Agent approved"),
    ("human_approved", "Human approved"),
    ("human_adjusted", "Human adjusted"),
    ("rejected", "Rejected / No order"),
)

RISK_LEVELS = (
    ("all", "All risks"),
    ("stockout", "Stockout"),
    ("overstock", "Overstock"),
    ("balanced", "Balanced"),
    ("manual_review", "Manual review"),
    ("insufficient_data", "Insufficient data"),
)

DATE_PRESETS = (
    ("today", "Today"),
    ("last_7", "Last 7 Days"),
    ("last_10", "Last 10 Days"),
    ("last_30", "Last 30 Days"),
    ("this_month", "This Month"),
    ("last_month", "Last Month"),
    ("custom", "Custom Range"),
)


@dataclass(frozen=True)
class SummaryFilters:
    date_from: date
    date_to: date
    store_id: str | None = None
    sku: str | None = None
    category: str | None = None  # reserved; product master has no category today
    vendor: str | None = None
    decision_type: str = "all"
    risk_level: str = "all"
    sales_window_days: int = 30


def analytics_as_of_date() -> date:
    """Reference date for presets: latest of configured as-of, today, and DB activity."""
    candidates: list[date] = [datetime.now(timezone.utc).date()]
    try:
        candidates.append(pd.Timestamp(AS_OF_DATE).date())
    except Exception:  # noqa: BLE001
        pass
    try:
        init_db()
        with get_session() as session:
            for model, col in (
                (RecommendationRow, RecommendationRow.created_at),
                (OrderIntentRow, OrderIntentRow.created_at),
            ):
                latest = session.scalar(select(col).order_by(col.desc()).limit(1))
                if latest is not None:
                    candidates.append(_to_date(latest) or candidates[0])
    except Exception:  # noqa: BLE001
        pass
    return max(candidates)


def resolve_preset(preset: str, *, custom_from: date | None = None, custom_to: date | None = None) -> tuple[date, date]:
    as_of = analytics_as_of_date()
    if preset == "today":
        return as_of, as_of
    if preset == "last_7":
        return as_of - timedelta(days=6), as_of
    if preset == "last_10":
        return as_of - timedelta(days=9), as_of
    if preset == "last_30":
        return as_of - timedelta(days=29), as_of
    if preset == "this_month":
        return as_of.replace(day=1), as_of
    if preset == "last_month":
        first_this = as_of.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if preset == "custom" and custom_from and custom_to:
        start, end = (custom_from, custom_to) if custom_from <= custom_to else (custom_to, custom_from)
        return start, end
    return as_of - timedelta(days=29), as_of


def _to_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _in_range(value: datetime | date | None, start: date, end: date) -> bool:
    d = _to_date(value)
    return d is not None and start <= d <= end


def _classify_decision(
    rec: RecommendationRow,
    review: HumanReviewRow | None,
    intent: OrderIntentRow | None,
) -> str:
    disposition = (rec.disposition or "").strip()
    status = (rec.status or "").strip().lower()
    action = ((review.decision_action if review else None) or "").strip().lower()

    if disposition == "no_order" or status in {"rejected", "declined"} or action in {
        "decline",
        "reject",
        "rejected",
    }:
        return "rejected"

    if review is not None:
        if action in {"adjust", "manual_quantity"} or bool(review.override_used):
            return "human_adjusted"
        if action in {"approve", "approved"} or (review.quantity_source or "") == "agent":
            return "human_approved"
        if (review.human_proposed_quantity or 0) != (review.agent_recommended_quantity or 0):
            return "human_adjusted"
        return "human_approved"

    if disposition == "auto_release" or (
        intent is not None and (intent.released_by_type or "") == "agent_policy"
    ):
        return "agent_approved"

    if disposition == "human_review":
        return "human_approved" if status == "approved" else "rejected" if status in {
            "rejected",
            "declined",
        } else "pending"

    if intent is not None and (intent.released_by_type or "") == "human":
        return "human_approved"

    return "pending"


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return ((current - previous) / abs(previous)) * 100.0


def _format_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _metric_kpi(
    label: str,
    value: float | int | None,
    *,
    fmt: str = "raw",
) -> dict[str, Any]:
    if value is None:
        return {"label": label, "value": "—", "sub": NOT_ENOUGH_DATA_SUB}
    if fmt == "pct":
        display = f"{float(value):.1f}%"
    elif fmt == "money":
        display = _format_money(float(value))
    elif fmt == "int":
        display = f"{int(round(float(value))):,}"
    else:
        display = str(value)
    return {"label": label, "value": display}


def _load_filtered_daily_ledger(filters: SummaryFilters) -> pd.DataFrame:
    daily = csv_repository.get_inventory_daily_frame()
    if daily.empty:
        return daily
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    mask = (daily["date"] >= pd.Timestamp(filters.date_from)) & (
        daily["date"] <= pd.Timestamp(filters.date_to)
    )
    if filters.store_id:
        mask &= daily["store_id"] == filters.store_id
    if filters.sku:
        mask &= daily["sku"] == filters.sku
    return daily.loc[mask]


def _eligible_completed_orders(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if row["decision"] not in {"agent_approved", "human_approved", "human_adjusted"}:
            continue
        intent: OrderIntentRow | None = row["intent"]
        rec: RecommendationRow = row["recommendation"]
        qty = int(intent.quantity or 0) if intent is not None else 0
        if qty <= 0:
            continue
        order_date = _to_date(rec.created_at)
        if order_date is None:
            continue
        eligible.append(
            {
                "store_id": rec.store_id,
                "sku": rec.sku,
                "order_date": order_date,
            }
        )
    return eligible


def _post_order_stockout_rate(
    eligible: list[dict[str, Any]], ledger: pd.DataFrame
) -> float | None:
    if not eligible or ledger.empty:
        return None
    hits = 0
    for order in eligible:
        start = order["order_date"] + timedelta(days=1)
        end = order["order_date"] + timedelta(days=POST_ORDER_WINDOW_DAYS)
        window = ledger[
            (ledger["store_id"] == order["store_id"])
            & (ledger["sku"] == order["sku"])
            & (ledger["date"] >= pd.Timestamp(start))
            & (ledger["date"] <= pd.Timestamp(end))
            & (ledger["is_stockout"].astype(int) == 1)
        ]
        if not window.empty:
            hits += 1
    return (hits / len(eligible)) * 100.0


def _post_order_excess_rate(
    eligible: list[dict[str, Any]], ledger: pd.DataFrame
) -> float | None:
    if not eligible or ledger.empty:
        return None
    hits = 0
    for order in eligible:
        start = order["order_date"] + timedelta(days=1)
        end = order["order_date"] + timedelta(days=POST_ORDER_WINDOW_DAYS)
        window = ledger[
            (ledger["store_id"] == order["store_id"])
            & (ledger["sku"] == order["sku"])
            & (ledger["date"] >= pd.Timestamp(start))
            & (ledger["date"] <= pd.Timestamp(end))
        ]
        if window.empty:
            continue
        excess = False
        for _, day in window.iterrows():
            ads = float(day["expected_demand"] or 0)
            if ads <= 0:
                ads = 0.2
            dos = float(day["ending_on_hand"]) / ads
            if dos > EXCESS_COVER_DAYS:
                excess = True
                break
        if excess:
            hits += 1
    return (hits / len(eligible)) * 100.0


def _ledger_stockout_totals(ledger: pd.DataFrame) -> tuple[int, float, float]:
    if ledger.empty:
        return 0, 0.0, 0.0
    oos = ledger.loc[ledger["is_stockout"].astype(int) == 1].copy()
    if oos.empty:
        return 0, 0.0, 0.0
    lost_units = 0.0
    lost_revenue = 0.0
    for _, row in oos.iterrows():
        expected = float(row["expected_demand"] or 0)
        sold = float(row["units_sold"] or 0)
        lost = max(expected - sold, 0.0)
        lost_units += lost
        lost_revenue += lost * float(row["retail_price"] or 0)
    return len(oos), lost_units, lost_revenue


def filter_options() -> dict[str, Any]:
    stores = product_service.list_stores()
    vendors: set[str] = set()
    skus: list[dict[str, str]] = []
    seen_sku: set[str] = set()
    for store in stores:
        sid = store["store_id"]
        for sku in product_service.list_store_skus(sid):
            if sku in seen_sku:
                continue
            seen_sku.add(sku)
            try:
                product = product_service.get_product_details(sku)
                name = product.product_name
            except Exception:  # noqa: BLE001
                name = sku
            skus.append({"sku": sku, "label": f"{sku} — {name}"})
    init_db()
    with get_session() as session:
        for row in session.scalars(select(OrderIntentRow.vendor).distinct()):
            if row:
                vendors.add(str(row))
        for row in session.scalars(select(RecommendationRow).limit(500)):
            # vendor not on recommendation; intents cover vendors
            pass
    if not vendors:
        vendors.add("Demo Vendor Co.")
    return {
        "stores": stores,
        "skus": sorted(skus, key=lambda x: x["sku"]),
        "vendors": sorted(vendors),
        "categories": [],  # product master has no category field
        "decision_types": list(DECISION_TYPES),
        "risk_levels": list(RISK_LEVELS),
        "date_presets": list(DATE_PRESETS),
        "as_of": analytics_as_of_date().isoformat(),
    }


def _load_bundle(filters: SummaryFilters) -> dict[str, Any]:
    init_db()
    start_dt = datetime.combine(filters.date_from, datetime.min.time())
    end_dt = datetime.combine(filters.date_to, datetime.max.time())
    period_days = max((filters.date_to - filters.date_from).days + 1, 1)
    prev_to = filters.date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_days - 1)

    with get_session() as session:
        rec_stmt = select(RecommendationRow).where(
            RecommendationRow.created_at >= start_dt,
            RecommendationRow.created_at <= end_dt,
        )
        if filters.store_id:
            rec_stmt = rec_stmt.where(RecommendationRow.store_id == filters.store_id)
        if filters.sku:
            rec_stmt = rec_stmt.where(RecommendationRow.sku == filters.sku)
        if filters.risk_level and filters.risk_level != "all":
            rec_stmt = rec_stmt.where(RecommendationRow.risk_level == filters.risk_level)
        recommendations = list(session.scalars(rec_stmt.order_by(RecommendationRow.created_at.desc()).limit(5000)))

        prev_recs = list(
            session.scalars(
                select(RecommendationRow)
                .where(
                    RecommendationRow.created_at
                    >= datetime.combine(prev_from, datetime.min.time()),
                    RecommendationRow.created_at
                    <= datetime.combine(prev_to, datetime.max.time()),
                )
                .limit(5000)
            )
        )

        rec_ids = [r.recommendation_id for r in recommendations]
        reviews_by_rec: dict[str, HumanReviewRow] = {}
        if rec_ids:
            for row in session.scalars(
                select(HumanReviewRow).where(HumanReviewRow.recommendation_id.in_(rec_ids))
            ):
                existing = reviews_by_rec.get(row.recommendation_id)
                if existing is None or row.submitted_at >= existing.submitted_at:
                    reviews_by_rec[row.recommendation_id] = row

        intent_stmt = select(OrderIntentRow).where(
            OrderIntentRow.created_at >= start_dt,
            OrderIntentRow.created_at <= end_dt,
        )
        if filters.store_id:
            intent_stmt = intent_stmt.where(OrderIntentRow.store_id == filters.store_id)
        if filters.sku:
            intent_stmt = intent_stmt.where(OrderIntentRow.sku == filters.sku)
        if filters.vendor:
            intent_stmt = intent_stmt.where(OrderIntentRow.vendor == filters.vendor)
        intents = list(session.scalars(intent_stmt.limit(5000)))
        intents_by_rec = {
            i.recommendation_id: i for i in intents if i.recommendation_id
        }

        prev_intents = list(
            session.scalars(
                select(OrderIntentRow)
                .where(
                    OrderIntentRow.created_at
                    >= datetime.combine(prev_from, datetime.min.time()),
                    OrderIntentRow.created_at
                    <= datetime.combine(prev_to, datetime.max.time()),
                )
                .limit(5000)
            )
        )

    sales_df = csv_repository.get_sales_frame().copy()
    if not sales_df.empty:
        sales_df["date"] = pd.to_datetime(sales_df["date"]).dt.normalize()
        mask = (sales_df["date"] >= pd.Timestamp(filters.date_from)) & (
            sales_df["date"] <= pd.Timestamp(filters.date_to)
        )
        if filters.store_id:
            mask &= sales_df["store_id"] == filters.store_id
        if filters.sku:
            mask &= sales_df["sku"] == filters.sku
        sales_df = sales_df.loc[mask].copy()

    classified: list[dict[str, Any]] = []
    for rec in recommendations:
        review = reviews_by_rec.get(rec.recommendation_id)
        intent = intents_by_rec.get(rec.recommendation_id)
        decision = _classify_decision(rec, review, intent)
        if decision == "pending":
            # Undecided review items are excluded from ownership totals unless filtered explicitly
            if filters.decision_type not in {"all", "human_approved"}:
                continue
            if filters.decision_type == "human_approved":
                decision = "human_approved"
        if filters.decision_type != "all" and decision != filters.decision_type:
            continue
        if filters.vendor:
            vendor = (intent.vendor if intent else None) or "Demo Vendor Co."
            if vendor != filters.vendor:
                continue
        classified.append(
            {
                "recommendation": rec,
                "review": review,
                "intent": intent,
                "decision": decision,
            }
        )

    return {
        "filters": filters,
        "period_days": period_days,
        "prev_from": prev_from,
        "prev_to": prev_to,
        "rows": classified,
        "prev_recommendations": prev_recs,
        "intents": intents,
        "prev_intents": prev_intents,
        "sales_df": sales_df,
        "reviews_by_rec": reviews_by_rec,
    }


def build_summary_dashboard(filters: SummaryFilters) -> dict[str, Any]:
    """Single filtered pass — all Summary sections read from this payload."""
    bundle = _load_bundle(filters)
    rows: list[dict[str, Any]] = bundle["rows"]
    sales_df: pd.DataFrame = bundle["sales_df"]
    intents: list[OrderIntentRow] = bundle["intents"]
    prev_intents: list[OrderIntentRow] = bundle["prev_intents"]
    period_days = bundle["period_days"]

    ownership_counts = {
        "agent_approved": 0,
        "human_approved": 0,
        "human_adjusted": 0,
        "rejected": 0,
    }
    for row in rows:
        key = row["decision"]
        if key in ownership_counts:
            ownership_counts[key] += 1
        elif key == "pending":
            # undecided human_review still counts toward intervention pressure
            ownership_counts["human_approved"] += 0

    decided = sum(ownership_counts.values())
    ownership = []
    for key, label in (
        ("agent_approved", "Agent approved"),
        ("human_approved", "Human approved"),
        ("human_adjusted", "Human adjusted"),
        ("rejected", "Rejected / No order"),
    ):
        count = ownership_counts[key]
        ownership.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "percent": round((count / decided) * 100, 1) if decided else 0.0,
            }
        )

    units_ordered = sum(int(i.quantity or 0) for i in intents)
    order_value = sum(float(i.amount or 0) for i in intents)
    prev_units = sum(int(i.quantity or 0) for i in prev_intents)
    prev_value = sum(float(i.amount or 0) for i in prev_intents)
    prev_decisions = len(bundle["prev_recommendations"])

    agent_orders = sum(
        1 for i in intents if (i.released_by_type or "") == "agent_policy"
    )
    human_orders = sum(1 for i in intents if (i.released_by_type or "") == "human")
    human_adjusted = ownership_counts["human_adjusted"]
    rejected = ownership_counts["rejected"]
    skus_replenished = len({(r["recommendation"].store_id, r["recommendation"].sku) for r in rows if r["decision"] in {"agent_approved", "human_approved", "human_adjusted"} and (r["intent"] or r["recommendation"].agent_recommended_quantity)})

    period_summary = [
        _kpi("Replenishment decisions", len(rows), prev_decisions, period_days),
        _kpi("Units ordered", units_ordered, prev_units, period_days, fmt="int"),
        _kpi("Total order value", order_value, prev_value, period_days, fmt="money"),
        _kpi("Agent-approved orders", agent_orders, None, period_days, fmt="int"),
        _kpi("Human-approved orders", human_orders, None, period_days, fmt="int"),
        _kpi(
            "Human-adjusted / rejected",
            human_adjusted + rejected,
            None,
            period_days,
            fmt="int",
        ),
        _kpi("SKUs replenished", skus_replenished, None, period_days, fmt="int"),
    ]

    return {
        "filters": {
            "date_from": filters.date_from.isoformat(),
            "date_to": filters.date_to.isoformat(),
            "period_days": period_days,
            "previous_period": f"{bundle['prev_from'].isoformat()} → {bundle['prev_to'].isoformat()}",
        },
        "period_summary": period_summary,
        "decision_ownership": ownership,
        "agent_vs_human_trend": _agent_human_trend(rows, filters),
        "top_overrides": _top_overrides(rows),
        "sales_vs_replenishment": _sales_vs_replenishment(sales_df, intents, filters),
        "sales_trend": _sales_trend(sales_df, filters),
        "recommendation_performance": {
            "available": False,
            "message": OUTCOME_UNAVAILABLE,
            "detail": "Post-order stockout, excess, and forecast-alignment outcomes are not persisted.",
        },
        "stockout_analysis": _stockout_analysis(rows, filters),
        "stockout_horizon": _stockout_horizon(rows),
        "excess_inventory": _excess_inventory(filters),
        "inventory_efficiency": {
            "available": False,
            "message": UNAVAILABLE,
            "detail": "Turnover / DIO require multi-period inventory valuation history.",
        },
        "vendor_performance": _vendor_performance(intents),
        "product_performance": _product_quadrant(rows),
        "replenishment_efficiency": _replenishment_efficiency(rows, ownership_counts, filters),
        "historical_decisions": _historical_rows(rows, sales_df),
        "data_notes": [
            "Sales history comes from the demo sales feed (limited lookback).",
            "Lost revenue, fill rate, late delivery %, and post-order outcomes are not available in persisted data.",
            "Category is not present on the product master — category filter is inactive.",
        ],
    }


def _kpi(
    label: str,
    value: float | int,
    previous: float | int | None,
    period_days: int,
    *,
    fmt: str = "int",
) -> dict[str, Any]:
    change = _pct_change(float(value), float(previous)) if previous is not None else None
    if fmt == "money":
        display = _format_money(float(value))
    else:
        display = f"{int(round(float(value))):,}"
    sub = None
    if change is not None:
        arrow = "↑" if change >= 0 else "↓"
        sub = f"{arrow} {abs(change):.1f}% vs previous {period_days} days"
    return {
        "label": label,
        "value": display,
        "raw": value,
        "change_pct": change,
        "sub": sub,
    }


def _agent_human_trend(rows: list[dict[str, Any]], filters: SummaryFilters) -> dict[str, Any]:
    if not rows:
        return {"available": False, "message": UNAVAILABLE, "points": []}
    span = (filters.date_to - filters.date_from).days + 1
    weekly = span > 21
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"agent": 0, "human": 0, "total": 0})
    for row in rows:
        rec: RecommendationRow = row["recommendation"]
        d = _to_date(rec.created_at)
        if d is None:
            continue
        if weekly:
            key = (d - timedelta(days=d.weekday())).isoformat()
        else:
            key = d.isoformat()
        buckets[key]["total"] += 1
        if row["decision"] == "agent_approved":
            buckets[key]["agent"] += 1
        else:
            buckets[key]["human"] += 1
    points = []
    for key in sorted(buckets):
        total = buckets[key]["total"] or 1
        points.append(
            {
                "period": key,
                "agent_pct": round(buckets[key]["agent"] / total * 100, 1),
                "human_pct": round(buckets[key]["human"] / total * 100, 1),
                "total": buckets[key]["total"],
            }
        )
    return {
        "available": True,
        "grain": "week" if weekly else "day",
        "points": points,
    }


def _top_overrides(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_sku: dict[str, dict[str, Any]] = {}
    for row in rows:
        rec: RecommendationRow = row["recommendation"]
        review: HumanReviewRow | None = row["review"]
        key = f"{rec.store_id}|{rec.sku}"
        slot = by_sku.setdefault(
            key,
            {
                "product": rec.product_name or rec.sku,
                "sku": rec.sku,
                "store_id": rec.store_id,
                "agent_recommendations": 0,
                "human_overrides": 0,
                "adj_sum": 0.0,
                "adj_n": 0,
            },
        )
        slot["agent_recommendations"] += 1
        if review and (review.override_used or row["decision"] == "human_adjusted"):
            slot["human_overrides"] += 1
            slot["adj_sum"] += float(review.difference_units or 0)
            slot["adj_n"] += 1
    table = []
    for slot in by_sku.values():
        recs = slot["agent_recommendations"]
        overrides = slot["human_overrides"]
        if overrides == 0:
            continue
        table.append(
            {
                "product": slot["product"],
                "sku": slot["sku"],
                "store_id": slot["store_id"],
                "agent_recommendations": recs,
                "human_overrides": overrides,
                "override_pct": round(overrides / recs * 100, 1) if recs else 0.0,
                "avg_qty_adjustment": round(slot["adj_sum"] / slot["adj_n"], 1)
                if slot["adj_n"]
                else 0.0,
            }
        )
    table.sort(key=lambda r: (-r["override_pct"], -r["human_overrides"]))
    return {
        "available": bool(table),
        "message": UNAVAILABLE if not table else None,
        "rows": table[:25],
    }


def _sales_vs_replenishment(
    sales_df: pd.DataFrame,
    intents: list[OrderIntentRow],
    filters: SummaryFilters,
) -> dict[str, Any]:
    sold_by_day: dict[str, float] = defaultdict(float)
    if not sales_df.empty:
        grouped = sales_df.groupby(sales_df["date"].dt.date)["units_sold"].sum()
        for d, units in grouped.items():
            sold_by_day[pd.Timestamp(d).date().isoformat()] = float(units)

    ordered_by_day: dict[str, float] = defaultdict(float)
    for intent in intents:
        d = _to_date(intent.created_at)
        if d is None:
            continue
        ordered_by_day[d.isoformat()] += float(intent.quantity or 0)

    days = []
    cursor = filters.date_from
    while cursor <= filters.date_to:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)

    if not sold_by_day and not ordered_by_day:
        return {"available": False, "message": UNAVAILABLE, "points": []}

    points = []
    for day in days:
        sold = sold_by_day.get(day, 0.0)
        ordered = ordered_by_day.get(day, 0.0)
        points.append(
            {
                "date": day,
                "units_sold": sold,
                "units_ordered": ordered,
                "difference": sold - ordered,
                "ending_inventory": None,
            }
        )
    return {
        "available": True,
        "points": points,
        "ending_inventory_available": False,
        "note": "Ending inventory after order is not persisted.",
    }


def _sales_trend(sales_df: pd.DataFrame, filters: SummaryFilters) -> dict[str, Any]:
    window = max(int(filters.sales_window_days or 30), 1)
    end = filters.date_to
    start = end - timedelta(days=window - 1)
    if sales_df.empty:
        return {
            "available": False,
            "message": UNAVAILABLE,
            "window_days": window,
            "sku_selected": bool(filters.sku),
        }
    frame = sales_df.copy()
    frame = frame[
        (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))
    ]
    if frame.empty:
        return {
            "available": False,
            "message": UNAVAILABLE,
            "window_days": window,
            "sku_selected": bool(filters.sku),
        }
    daily = frame.groupby(frame["date"].dt.date)["units_sold"].sum().sort_index()
    points = [
        {"date": pd.Timestamp(d).date().isoformat(), "units_sold": float(v)}
        for d, v in daily.items()
    ]
    total = float(daily.sum())
    avg = total / window
    stats = {
        "units_sold": total,
        "avg_daily_sales": round(avg, 2),
        "highest_day": {
            "date": pd.Timestamp(daily.idxmax()).date().isoformat(),
            "units": float(daily.max()),
        },
        "lowest_day": {
            "date": pd.Timestamp(daily.idxmin()).date().isoformat(),
            "units": float(daily.min()),
        },
    }
    # previous equivalent window
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window - 1)
    prev = csv_repository.get_sales_frame().copy()
    change = None
    if not prev.empty:
        prev["date"] = pd.to_datetime(prev["date"]).dt.normalize()
        pmask = (prev["date"] >= pd.Timestamp(prev_start)) & (
            prev["date"] <= pd.Timestamp(prev_end)
        )
        if filters.store_id:
            pmask &= prev["store_id"] == filters.store_id
        if filters.sku:
            pmask &= prev["sku"] == filters.sku
        prev_total = float(prev.loc[pmask, "units_sold"].sum())
        change = _pct_change(total, prev_total)
    stats["change_pct"] = change
    return {
        "available": True,
        "window_days": window,
        "sku_selected": bool(filters.sku),
        "points": points,
        "stats": stats if filters.sku else None,
        "stats_note": None
        if filters.sku
        else "Select a Product / SKU filter to see SKU-level sales stats.",
    }


def _stockout_analysis(
    rows: list[dict[str, Any]], filters: SummaryFilters
) -> dict[str, Any]:
    stockout_rows = [
        r
        for r in rows
        if (r["recommendation"].risk_level or "") == "stockout"
    ]
    if not stockout_rows:
        return {
            "available": False,
            "message": UNAVAILABLE,
            "kpis": [],
            "worst": [],
        }
    ledger = _load_filtered_daily_ledger(filters)
    has_ledger = not ledger.empty
    stockout_days, lost_units, lost_revenue = _ledger_stockout_totals(ledger)

    # Per store/SKU aggregates for the worst-offenders table.
    ledger_agg: dict[tuple[str, str], dict[str, Any]] = {}
    if not ledger.empty:
        oos = ledger.loc[ledger["is_stockout"].astype(int) == 1]
        for _, row in oos.iterrows():
            key = (str(row["store_id"]), str(row["sku"]))
            slot = ledger_agg.setdefault(
                key,
                {"stockout_days": 0, "lost_units": 0.0, "lost_revenue": 0.0},
            )
            expected = float(row["expected_demand"] or 0)
            sold = float(row["units_sold"] or 0)
            lost = max(expected - sold, 0.0)
            slot["stockout_days"] += 1
            slot["lost_units"] += lost
            slot["lost_revenue"] += lost * float(row["retail_price"] or 0)

    by_product: dict[str, dict[str, Any]] = {}
    for row in stockout_rows:
        rec: RecommendationRow = row["recommendation"]
        key = f"{rec.store_id}|{rec.sku}"
        slot = by_product.setdefault(
            key,
            {
                "product": rec.product_name or rec.sku,
                "store": product_service.store_display_name(rec.store_id),
                "sku": rec.sku,
                "store_id": rec.store_id,
                "events": 0,
                "dos_values": [],
            },
        )
        slot["events"] += 1
        if rec.days_of_supply is not None:
            slot["dos_values"].append(float(rec.days_of_supply))
    worst = []
    for slot in by_product.values():
        agg = ledger_agg.get((slot["store_id"], slot["sku"]), {})
        sd = agg.get("stockout_days", 0)
        lu = agg.get("lost_units", 0.0)
        lr = agg.get("lost_revenue", 0.0)
        worst.append(
            {
                "product": slot["product"],
                "store": slot["store"],
                "stockout_days": sd if sd else "—",
                "lost_units": f"{lu:,.0f}" if lu else "—",
                "lost_revenue": _format_money(lr) if lr else "—",
                "risk_events": slot["events"],
                "avg_days_of_supply": round(
                    sum(slot["dos_values"]) / len(slot["dos_values"]), 1
                )
                if slot["dos_values"]
                else None,
            }
        )
    worst.sort(key=lambda r: (-(r["stockout_days"] if isinstance(r["stockout_days"], int) else 0), -r["risk_events"]))
    return {
        "available": True,
        "kpis": [
            {"label": "Stockout-risk decisions", "value": str(len(stockout_rows))},
            _metric_kpi("Stockout days", stockout_days if has_ledger else None, fmt="int"),
            _metric_kpi(
                "Estimated lost units",
                lost_units if has_ledger else None,
                fmt="int",
            ),
            _metric_kpi(
                "Estimated lost revenue",
                lost_revenue if has_ledger else None,
                fmt="money",
            ),
        ],
        "worst": worst[:20],
    }


def _stockout_horizon(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = {
        "< 1 day": 0,
        "1–3 days": 0,
        "4–7 days": 0,
        "> 7 days": 0,
    }
    counted = 0
    for row in rows:
        rec: RecommendationRow = row["recommendation"]
        if (rec.risk_level or "") != "stockout":
            continue
        dos = rec.days_of_supply
        if dos is None:
            continue
        counted += 1
        if dos < 1:
            buckets["< 1 day"] += 1
        elif dos <= 3:
            buckets["1–3 days"] += 1
        elif dos <= 7:
            buckets["4–7 days"] += 1
        else:
            buckets["> 7 days"] += 1
    return {
        "available": counted > 0,
        "message": UNAVAILABLE if counted == 0 else None,
        "buckets": [{"label": k, "count": v} for k, v in buckets.items()],
        "note": "Buckets use days-of-supply on stockout-risk recommendations (projected coverage), not measured out-of-stock duration.",
    }


def _excess_inventory(filters: SummaryFilters) -> dict[str, Any]:
    try:
        inv_provider = get_inventory_provider()
        product_provider = get_product_provider()
    except Exception:  # noqa: BLE001
        return {"available": False, "message": UNAVAILABLE, "kpis": [], "rows": []}

    stores = (
        [{"store_id": filters.store_id}]
        if filters.store_id
        else product_service.list_stores()
    )
    # Latest recommendation DoS / ADS by store+sku within filter window (fallback snapshot)
    latest_meta: dict[tuple[str, str], RecommendationRow] = {}
    init_db()
    with get_session() as session:
        stmt = select(RecommendationRow).order_by(RecommendationRow.created_at.desc()).limit(2000)
        if filters.store_id:
            stmt = stmt.where(RecommendationRow.store_id == filters.store_id)
        if filters.sku:
            stmt = stmt.where(RecommendationRow.sku == filters.sku)
        for rec in session.scalars(stmt):
            key = (rec.store_id, rec.sku)
            if key not in latest_meta:
                latest_meta[key] = rec

    slow = []
    high_dos = 0
    excess_units = 0.0
    tied_value = 0.0
    for store in stores:
        sid = store["store_id"]
        try:
            skus = product_service.list_store_skus(sid)
        except Exception:  # noqa: BLE001
            continue
        for sku in skus:
            if filters.sku and sku != filters.sku:
                continue
            try:
                result = inv_provider.get_inventory_position(sid, sku)
            except Exception:  # noqa: BLE001
                continue
            if result is None:
                continue
            position = getattr(result, "position", result)
            on_hand = int(getattr(position, "on_hand", 0) or 0)
            meta = latest_meta.get((sid, sku))
            ads = float(meta.average_daily_sales) if meta else 0.0
            dos = float(meta.days_of_supply) if meta and meta.days_of_supply is not None else (
                (on_hand / ads) if ads > 0 else None
            )
            if dos is None:
                continue
            if dos < 21:
                continue
            high_dos += 1
            target_cover = 14.0
            excess = max(0.0, on_hand - ads * target_cover) if ads > 0 else float(on_hand)
            excess_units += excess
            unit_cost = 0.0
            product_name = sku
            try:
                product = product_provider.get_product(sku)
                if product:
                    product_name = product.product_name or sku
                    unit_cost = float(getattr(product, "unit_cost", 0) or 0)
            except Exception:  # noqa: BLE001
                pass
            value = excess * unit_cost if unit_cost else None
            if value:
                tied_value += value
            # days since last sale from sales CSV
            sales = csv_repository.get_sales_frame()
            days_since_sale = None
            if not sales.empty:
                sales = sales.copy()
                sales["date"] = pd.to_datetime(sales["date"])
                mask = (sales["store_id"] == sid) & (sales["sku"] == sku) & (sales["units_sold"] > 0)
                subset = sales.loc[mask]
                if not subset.empty:
                    last = subset["date"].max().date()
                    days_since_sale = (analytics_as_of_date() - last).days
            slow.append(
                {
                    "product": product_name,
                    "store": product_service.store_display_name(sid),
                    "sku": sku,
                    "days_of_supply": round(dos, 1),
                    "units_on_hand": on_hand,
                    "sales_velocity": round(ads, 2),
                    "inventory_value": _format_money(on_hand * unit_cost) if unit_cost else UNAVAILABLE,
                    "days_since_last_sale": days_since_sale
                    if days_since_sale is not None
                    else UNAVAILABLE,
                    "excess_units": round(excess, 1),
                }
            )
    slow.sort(key=lambda r: -r["days_of_supply"])
    return {
        "available": bool(slow),
        "message": UNAVAILABLE if not slow else None,
        "kpis": [
            {"label": "High days-of-supply SKUs", "value": str(high_dos)},
            {"label": "Excess units (vs 14-day cover)", "value": f"{excess_units:,.0f}"},
            {
                "label": "Inventory value tied up",
                "value": _format_money(tied_value) if tied_value else UNAVAILABLE,
            },
        ],
        "rows": slow[:25],
        "note": "Excess uses on-hand vs 14× average daily sales from the latest recommendation snapshot.",
    }


def _vendor_performance(intents: list[OrderIntentRow]) -> dict[str, Any]:
    by_vendor: dict[str, dict[str, Any]] = {}
    for intent in intents:
        vendor = intent.vendor or "Unknown"
        slot = by_vendor.setdefault(
            vendor,
            {"orders": 0, "units": 0, "spend": 0.0},
        )
        slot["orders"] += 1
        slot["units"] += int(intent.quantity or 0)
        slot["spend"] += float(intent.amount or 0)
    if not by_vendor:
        return {"available": False, "message": UNAVAILABLE, "rows": []}
    rows = []
    for vendor, slot in sorted(by_vendor.items(), key=lambda x: -x[1]["spend"]):
        rows.append(
            {
                "vendor": vendor,
                "orders": slot["orders"],
                "units": slot["units"],
                "spend": _format_money(slot["spend"]),
                "avg_lead_time": UNAVAILABLE,
                "fill_rate": UNAVAILABLE,
                "late_delivery_pct": UNAVAILABLE,
            }
        )
    return {
        "available": True,
        "rows": rows,
        "note": "Lead time, fill rate, and late delivery % require receiving/ASN data — not persisted.",
    }


def _product_quadrant(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[tuple[str, str], RecommendationRow] = {}
    for row in rows:
        rec: RecommendationRow = row["recommendation"]
        key = (rec.store_id, rec.sku)
        if key not in latest:
            latest[key] = rec
    points = []
    for rec in latest.values():
        dos = rec.days_of_supply
        ads = rec.average_daily_sales
        if dos is None or ads is None:
            continue
        points.append(
            {
                "sku": rec.sku,
                "product": rec.product_name or rec.sku,
                "store": product_service.store_display_name(rec.store_id),
                "store_id": rec.store_id,
                "days_of_supply": float(dos),
                "sales_velocity": float(ads),
                "risk_level": rec.risk_level,
            }
        )
    if not points:
        return {"available": False, "message": UNAVAILABLE, "points": []}
    dos_vals = [p["days_of_supply"] for p in points]
    vel_vals = [p["sales_velocity"] for p in points]
    mid_dos = sorted(dos_vals)[len(dos_vals) // 2]
    mid_vel = sorted(vel_vals)[len(vel_vals) // 2]
    for p in points:
        high_sales = p["sales_velocity"] >= mid_vel
        low_inv = p["days_of_supply"] < mid_dos
        if high_sales and low_inv:
            p["quadrant"] = "Stockout risk"
        elif high_sales and not low_inv:
            p["quadrant"] = "Ideal"
        elif not high_sales and not low_inv:
            p["quadrant"] = "Slow movers"
        else:
            p["quadrant"] = "Potential over-ordering"
    return {
        "available": True,
        "points": points,
        "mid_days_of_supply": mid_dos,
        "mid_sales_velocity": mid_vel,
    }


def _replenishment_efficiency(
    rows: list[dict[str, Any]],
    ownership: dict[str, int],
    filters: SummaryFilters,
) -> dict[str, Any]:
    total = sum(ownership.values())
    if total == 0:
        return {"available": False, "message": UNAVAILABLE, "metrics": []}
    accepted = ownership["agent_approved"] + ownership["human_approved"]
    overrides = ownership["human_adjusted"]
    adj_mags = []
    for row in rows:
        review = row["review"]
        if review and row["decision"] == "human_adjusted":
            adj_mags.append(abs(float(review.difference_percent or 0)))
    ledger = _load_filtered_daily_ledger(filters)
    eligible = _eligible_completed_orders(rows)
    post_stockout = _post_order_stockout_rate(eligible, ledger)
    post_excess = _post_order_excess_rate(eligible, ledger)
    metrics = [
        {
            "label": "Recommendation acceptance rate",
            "value": f"{(accepted / total) * 100:.1f}%",
        },
        {
            "label": "Override rate",
            "value": f"{(overrides / total) * 100:.1f}%",
        },
        (
            {
                "label": "Average override magnitude",
                "value": f"{sum(adj_mags) / len(adj_mags):.1f}%",
            }
            if adj_mags
            else {
                "label": "Average override magnitude",
                "value": "—",
                "sub": NOT_ENOUGH_DATA_SUB,
            }
        ),
        _metric_kpi("Post-order stockout rate", post_stockout, fmt="pct"),
        _metric_kpi("Excess-after-order rate", post_excess, fmt="pct"),
    ]
    return {"available": True, "metrics": metrics}


def _historical_rows(rows: list[dict[str, Any]], sales_df: pd.DataFrame) -> list[dict[str, Any]]:
    label_map = {
        "agent_approved": "Agent approved",
        "human_approved": "Human approved",
        "human_adjusted": "Human adjusted",
        "rejected": "Rejected",
        "pending": "Pending",
    }
    out = []
    for row in rows[:200]:
        rec: RecommendationRow = row["recommendation"]
        review: HumanReviewRow | None = row["review"]
        intent: OrderIntentRow | None = row["intent"]
        agent_qty = rec.agent_recommended_quantity
        final_qty = (
            intent.quantity
            if intent is not None
            else (review.human_proposed_quantity if review else agent_qty)
        )
        sales_after = UNAVAILABLE
        created = _to_date(rec.created_at)
        if created is not None and not sales_df.empty:
            window = sales_df[
                (sales_df["store_id"] == rec.store_id)
                & (sales_df["sku"] == rec.sku)
                & (sales_df["date"] > pd.Timestamp(created))
                & (sales_df["date"] <= pd.Timestamp(created + timedelta(days=7)))
            ]
            if not window.empty:
                sales_after = f"{float(window['units_sold'].sum()):.0f} (7d)"
        out.append(
            {
                "date": created.isoformat() if created else "—",
                "product": rec.product_name or rec.sku,
                "sku": rec.sku,
                "store": product_service.store_display_name(rec.store_id),
                "store_id": rec.store_id,
                "agent_quantity": agent_qty,
                "final_quantity": final_qty,
                "decision": label_map.get(row["decision"], row["decision"]),
                "sales_after_order": sales_after,
                "outcome": UNAVAILABLE
                if sales_after == UNAVAILABLE
                else "Sales observed after decision date",
                "recommendation_id": rec.recommendation_id,
            }
        )
    return out

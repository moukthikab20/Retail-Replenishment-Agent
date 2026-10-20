"""Generate deterministic expanded demo CSVs + historical workflow rows.

Writes products/inventory/sales under data/ and seeds recommendations,
reviews, order intents, and runs for Summary analytics — without changing
policy formulas or live replenishment logic.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from config import AS_OF_DATE, DATA_DIR
from database.connection import get_session, init_db
from database.models import (
    HumanReviewRow,
    OrderIntentRow,
    PurchaseOrderRow,
    RecommendationRow,
    ReplenishmentRunItemRow,
    ReplenishmentRunRow,
)
from repositories import csv_repository
from services.demo_catalog import (
    DEMO_HISTORY_SEED,
    HIGH_OVERRIDE_SKUS,
    LOW_OVERRIDE_SKUS,
    PRESERVED_INVENTORY,
    PRODUCT_BY_SKU,
    PRODUCTS,
    STORES,
    VENDOR_BY_ID,
    VENDORS,
    product_retail_price,
)

HISTORY_DAYS = 90
HISTORY_META_FILENAME = "demo_history_meta.json"


def history_meta_path(data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / HISTORY_META_FILENAME


def resolve_history_seed(seed: int | None = None, *, data_dir: Path | None = None) -> int:
    """Resolve demo-history seed: explicit arg, persisted meta, or catalog default."""
    if seed is not None:
        return int(seed)
    path = history_meta_path(data_dir)
    if path.exists():
        try:
            return int(json.loads(path.read_text(encoding="utf-8")).get("seed", DEMO_HISTORY_SEED))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return DEMO_HISTORY_SEED


def summarize_decision_outcomes(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize generated demo decisions into UI-aligned outcome buckets."""
    disposition_counts: dict[str, int] = {
        "auto_release": 0,
        "human_review": 0,
        "blocked": 0,
        "no_order": 0,
    }
    human_adjusted_rejected = 0
    for decision in decisions:
        disposition = str(decision.get("disposition") or "")
        if disposition in disposition_counts:
            disposition_counts[disposition] += 1
        human_action = decision.get("human_action")
        if human_action in {"adjusted", "rejected"}:
            human_adjusted_rejected += 1
    total = len(decisions)
    pct = lambda n: round((n / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "auto_approved": disposition_counts["auto_release"],
        "needs_review": disposition_counts["human_review"],
        "blocked": disposition_counts["blocked"],
        "no_order": disposition_counts["no_order"],
        "human_adjusted_rejected": human_adjusted_rejected,
        "disposition_counts": disposition_counts,
        "percentages": {
            "auto_approved": pct(disposition_counts["auto_release"]),
            "needs_review": pct(disposition_counts["human_review"]),
            "blocked": pct(disposition_counts["blocked"]),
            "no_order": pct(disposition_counts["no_order"]),
            "human_adjusted_rejected": pct(human_adjusted_rejected),
        },
    }


def print_outcome_summary(summary: dict[str, Any], *, title: str) -> None:
    print(title)
    print(f"Historical decisions generated: {summary['total']}")
    print(f"Auto-approved: {summary['auto_approved']} ({summary['percentages']['auto_approved']}%)")
    print(f"Needs Review: {summary['needs_review']} ({summary['percentages']['needs_review']}%)")
    print(f"Blocked: {summary['blocked']} ({summary['percentages']['blocked']}%)")
    print(f"No Order: {summary['no_order']} ({summary['percentages']['no_order']}%)")
    print(
        "Human Adjusted/Rejected: "
        f"{summary['human_adjusted_rejected']} ({summary['percentages']['human_adjusted_rejected']}%)"
    )


def write_history_meta(
    *,
    seed: int,
    outcome_summary: dict[str, Any],
    data_dir: Path | None = None,
) -> str:
    path = history_meta_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed": int(seed),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcome_summary": outcome_summary,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def _query_db_outcome_counts() -> dict[str, Any]:
    """Read disposition counts from seeded recommendations."""
    from sqlalchemy import func, select

    init_db()
    with get_session() as session:
        disposition_rows = session.execute(
            select(RecommendationRow.disposition, func.count())
            .group_by(RecommendationRow.disposition)
        ).all()
        disposition_counts = {str(row[0] or "unknown"): int(row[1]) for row in disposition_rows}
        human_rows = session.execute(
            select(HumanReviewRow.decision_action, func.count())
            .group_by(HumanReviewRow.decision_action)
        ).all()
        human_actions = {str(row[0] or "unknown"): int(row[1]) for row in human_rows}
    total = sum(disposition_counts.values())
    auto_approved = disposition_counts.get("auto_release", 0)
    needs_review = disposition_counts.get("human_review", 0)
    blocked = disposition_counts.get("blocked", 0)
    no_order = disposition_counts.get("no_order", 0)
    human_adjusted_rejected = human_actions.get("adjust", 0) + human_actions.get("decline", 0)
    pct = lambda n: round((n / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "auto_approved": auto_approved,
        "needs_review": needs_review,
        "blocked": blocked,
        "no_order": no_order,
        "human_adjusted_rejected": human_adjusted_rejected,
        "disposition_counts": disposition_counts,
        "human_action_counts": human_actions,
        "percentages": {
            "auto_approved": pct(auto_approved),
            "needs_review": pct(needs_review),
            "blocked": pct(blocked),
            "no_order": pct(no_order),
            "human_adjusted_rejected": pct(human_adjusted_rejected),
        },
    }


def _as_of() -> date:
    """Demo clock for history end — later of configured AS_OF and UTC today.

    Summary analytics presets use max(AS_OF, today, latest DB activity). Ending
    history on that same clock keeps Last 7/10/30 windows populated.
    """
    configured = pd.Timestamp(AS_OF_DATE).date()
    today = datetime.now(timezone.utc).date()
    return max(configured, today)


def _history_dates() -> list[date]:
    end = _as_of() - timedelta(days=1)
    start = end - timedelta(days=HISTORY_DAYS - 1)
    out: list[date] = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _round_case(qty: float, pack: int) -> int:
    pack = max(int(pack or 1), 1)
    if qty <= 0:
        return 0
    return int(math.ceil(qty / pack) * pack)


def _weekday_factor(d: date, store: dict[str, Any], product: dict[str, Any]) -> float:
    wd = d.weekday()  # Mon=0
    base = 1.0
    if wd >= 5:
        base *= float(store.get("weekend_boost", 1.1))
        if product.get("beverage") or product.get("snack"):
            base *= 1.15
    else:
        # Downtown stronger weekdays
        if store["store_id"] == "ST001":
            base *= 1.12
        if wd in {0, 1}:  # Mon/Tue slightly softer convenience
            if store["store_id"] == "ST004":
                base *= 1.08
    return base


def _trend_factor(day_index: int, product: dict[str, Any], rng: random.Random) -> float:
    progress = day_index / max(HISTORY_DAYS - 1, 1)
    trend = product.get("trend", "flat")
    if trend == "up":
        return 0.88 + 0.28 * progress
    if trend == "down":
        return 1.18 - 0.32 * progress
    if trend == "spike":
        # Occasional weekend/promo spikes
        spike = 1.0
        if day_index % 17 == 0:
            spike = 1.55
        if day_index % 23 == 0:
            spike = 1.35
        return spike * (0.95 + 0.1 * math.sin(progress * math.pi * 2))
    return 1.0 + 0.04 * math.sin(progress * math.pi * 2 + rng.random())


def _profile_noise(profile: str, rng: random.Random, store_vol: float) -> float:
    if profile == "volatile":
        return rng.uniform(0.65, 1.45) * (1 + store_vol)
    if profile == "fast":
        return rng.uniform(0.85, 1.2)
    if profile == "slow":
        return rng.uniform(0.7, 1.15)
    return rng.uniform(0.88, 1.12)


def _store_product_factor(store: dict[str, Any], product: dict[str, Any]) -> float:
    factor = float(store["traffic"])
    if product.get("beverage") or product.get("snack"):
        factor *= float(store.get("beverage_snack_boost", 1.0))
    if product.get("essential"):
        factor *= float(store.get("essentials_boost", 1.0))
    if product.get("profile") == "slow":
        factor *= float(store.get("slow_bias", 1.0))
    if product.get("profile") == "fast":
        factor *= 0.95 + 0.1 * float(store.get("stockout_bias", 1.0))
    return factor


def generate_sales_rows(rng: random.Random) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dates = _history_dates()
    for store in STORES:
        for product in PRODUCTS:
            for idx, d in enumerate(dates):
                demand = (
                    float(product["base_demand"])
                    * _store_product_factor(store, product)
                    * _weekday_factor(d, store, product)
                    * _trend_factor(idx, product, rng)
                    * _profile_noise(product["profile"], rng, float(store["volatility"]))
                )
                # Riverside more variable; Flagship smoother floors
                if store["store_id"] == "ST005":
                    demand *= rng.uniform(0.75, 1.3)
                units = max(0, int(round(demand)))
                # Rare zero-sale days for slow movers
                if product["profile"] == "slow" and rng.random() < 0.12:
                    units = 0
                rows.append(
                    {
                        "date": d.isoformat(),
                        "store_id": store["store_id"],
                        "sku": product["sku"],
                        "units_sold": units,
                    }
                )
    return rows


def _trailing_ads(
    sales_map: dict[tuple[str, str, str], int],
    store: dict[str, Any],
    product: dict[str, Any],
    d: date,
    key: tuple[str, str],
) -> float:
    trail = []
    for back in range(1, 8):
        dd = d - timedelta(days=back)
        trail.append(sales_map.get((key[0], key[1], dd.isoformat()), 0))
    if trail:
        return max(sum(trail) / len(trail), 0.2)
    return max(
        float(product["base_demand"]) * _store_product_factor(store, product) * 0.9,
        0.3,
    )


def _trailing_sales(
    sales_map: dict[tuple[str, str, str], int],
    key: tuple[str, str],
    d: date,
    *,
    days: int = 7,
) -> list[int]:
    trail: list[int] = []
    for back in range(1, days + 1):
        dd = d - timedelta(days=back)
        trail.append(sales_map.get((key[0], key[1], dd.isoformat()), 0))
    return trail


def _assign_historical_disposition(
    *,
    rng: random.Random,
    store: dict[str, Any],
    product: dict[str, Any],
    d: date,
    oh: float,
    dos: float,
    ads: float,
    qty: int,
    pack: int,
    stockout_risk: bool,
    low_cover: bool,
    overstock: bool,
    large_order: bool,
    cover_target: float,
    trail: list[int],
    vendor: dict[str, Any],
) -> tuple[str, str, str | None]:
    """Assign demo-history disposition from inventory and policy context (not live agent)."""
    order_value = qty * float(product["unit_cost"])
    volatile = product["profile"] == "volatile"
    unreliable_vendor = float(vendor.get("reliability", 1.0)) < 0.86
    thin_history = sum(trail) < max(ads * 2.0, 1.5)
    near_threshold = cover_target * 0.88 <= dos <= cover_target * 1.18
    store_vol = float(store.get("volatility", 0.1))
    sku_num = int(str(product["sku"]).split("-")[-1])
    date_factor = ((d.toordinal() + sku_num) % 11) / 10.0

    data_gap = oh <= 0 and sum(trail) < max(1, int(ads * 0.75))

    if qty <= 0 and not stockout_risk:
        return "no_order", "balanced", None

    if overstock and not stockout_risk:
        if rng.random() < (0.12 + store_vol * 0.1):
            return "human_review", "overstock", None
        return "no_order", "overstock", None

    if data_gap and rng.random() < (0.3 + store_vol * 0.12):
        return "blocked", "insufficient_data", "Stale or incomplete inventory signal"
    if thin_history and rng.random() < (0.16 + store_vol * 0.1):
        return "blocked", "insufficient_data", "Insufficient demand history"
    if unreliable_vendor and rng.random() < (0.18 + date_factor * 0.06):
        return "blocked", "insufficient_data", "Vendor reliability below policy minimum"
    if stockout_risk and unreliable_vendor and rng.random() < 0.3:
        return "blocked", "insufficient_data", "Vendor reliability below policy minimum"
    if large_order and thin_history and rng.random() < 0.18:
        return "blocked", "manual_review", "High-value order requires data validation"
    if ads < 0.55 and rng.random() < 0.13:
        return "blocked", "insufficient_data", "Insufficient demand history"
    if volatile and thin_history and rng.random() < 0.14:
        return "blocked", "insufficient_data", "Insufficient demand history"

    if large_order:
        if order_value >= 460 or (unreliable_vendor and order_value >= 320):
            return "human_review", "manual_review", None
        if rng.random() < 0.34:
            return "human_review", "manual_review", None
        return "auto_release", "manual_review", None

    if stockout_risk:
        review_chance = 0.05 + store_vol * 0.07
        if order_value >= 320:
            review_chance += 0.1
        elif order_value >= 220:
            review_chance += 0.05
        if volatile:
            review_chance += 0.04
        if product["sku"] in HIGH_OVERRIDE_SKUS:
            review_chance += 0.04
        if product["sku"] in LOW_OVERRIDE_SKUS:
            review_chance -= 0.03
        if rng.random() < min(max(review_chance, 0.03), 0.16):
            return "human_review", "stockout", None
        return "auto_release", "stockout", None

    if volatile and (low_cover or near_threshold) and rng.random() < (0.1 + store_vol * 0.06):
        return "human_review", "manual_review", None

    if near_threshold and rng.random() < (0.06 + store_vol * 0.04):
        return "human_review", "manual_review", None

    if low_cover and not overstock:
        return "auto_release", "balanced" if dos >= 3 else "stockout", None

    return "auto_release", "balanced", None


def _simulate_inventory_and_decisions(
    sales_rows: list[dict[str, Any]],
    rng: random.Random,
    *,
    history_seed: int = DEMO_HISTORY_SEED,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Evolve inventory; emit ending inventory + decision/order history specs."""
    dates = _history_dates()
    sales_map: dict[tuple[str, str, str], int] = {
        (r["store_id"], r["sku"], r["date"]): int(r["units_sold"]) for r in sales_rows
    }

    # Starting inventory ~ capacity * (safety + 7*base)
    on_hand: dict[tuple[str, str], float] = {}
    in_transit: dict[tuple[str, str], list[tuple[date, int]]] = {}
    for store in STORES:
        for product in PRODUCTS:
            key = (store["store_id"], product["sku"])
            start = (
                float(product["safety_stock_units"])
                + float(product["base_demand"]) * 16 * float(store["capacity"])
            )
            if product["profile"] == "slow":
                start *= 1.6 * float(store.get("slow_bias", 1.0))
            if product["profile"] == "fast":
                start *= 0.85 / max(float(store.get("stockout_bias", 1.0)) ** 0.3, 0.8)
            on_hand[key] = max(float(product["safety_stock_units"]), start)
            in_transit[key] = []

    decisions: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    retail_by_sku = {p["sku"]: product_retail_price(p) for p in PRODUCTS}
    decision_counter = 0
    run_counter = 0

    # Decide ~every 7 days per store batch (keeps volume near 600–1000)
    batch_days = {d for i, d in enumerate(dates) if i % 7 == 0}

    for d in dates:
        # Receive in-transit
        for key, shipments in in_transit.items():
            remaining = []
            for arrive, qty in shipments:
                if arrive <= d:
                    on_hand[key] = on_hand.get(key, 0) + qty
                else:
                    remaining.append((arrive, qty))
            in_transit[key] = remaining

        # Sales + daily outcome ledger
        for store in STORES:
            for product in PRODUCTS:
                key = (store["store_id"], product["sku"])
                sold = sales_map.get((key[0], key[1], d.isoformat()), 0)
                on_hand[key] = max(0.0, on_hand.get(key, 0) - sold)
                ending = int(round(on_hand[key]))
                ads = _trailing_ads(sales_map, store, product, d, key)
                daily_rows.append(
                    {
                        "date": d.isoformat(),
                        "store_id": key[0],
                        "sku": key[1],
                        "units_sold": int(sold),
                        "ending_on_hand": ending,
                        "is_stockout": 1 if ending <= 0 else 0,
                        "retail_price": retail_by_sku[product["sku"]],
                        "expected_demand": round(ads, 3),
                    }
                )

        if d not in batch_days:
            continue

        run_counter += 1
        run_id = f"RUN-HIST-{history_seed:03d}-{run_counter:04d}"
        run_decisions = 0

        for store in STORES:
            for product in PRODUCTS:
                key = (store["store_id"], product["sku"])
                oh = on_hand.get(key, 0.0)
                pending = sum(q for _, q in in_transit.get(key, []))
                trail = _trailing_sales(sales_map, key, d)
                ads = _trailing_ads(sales_map, store, product, d, key)
                dos = (oh + pending) / ads if ads > 0 else 99.0
                safety = float(product["safety_stock_units"])
                cover_target = 7.0 + (VENDOR_BY_ID[product["vendor_id"]]["lead_time_days"] * 0.4)
                raw_need = max(0.0, ads * cover_target + safety - oh - pending)
                pack = int(product["case_pack_size"])
                qty = _round_case(raw_need, pack)
                vendor = VENDOR_BY_ID[product["vendor_id"]]

                low_cover = dos < cover_target * 0.55
                stockout_risk = oh <= 0 or dos < 1.35
                overstock = dos > 30 or (product["profile"] == "slow" and dos > 24)
                large_order = qty >= pack * 10 or (
                    qty * float(product["unit_cost"]) >= 320
                )
                needs_decision = (
                    stockout_risk
                    or low_cover
                    or overstock
                    or large_order
                    or (
                        product["profile"] == "volatile"
                        and dos < cover_target * 0.85
                        and rng.random() < 0.14
                    )
                )
                if overstock and not stockout_risk and not large_order and rng.random() < 0.84:
                    continue
                if not needs_decision:
                    # Sparse explicit no-order rows for analytics
                    if rng.random() > 0.012:
                        continue
                    disposition = "no_order"
                    qty = 0
                    risk = "balanced"
                    blocked_reason = None
                else:
                    # Quiet restock for skipped routine cycles (no decision row).
                    if (
                        low_cover
                        and not stockout_risk
                        and not overstock
                        and not large_order
                        and rng.random() < 0.7
                    ):
                        if qty > 0:
                            lead = int(vendor["lead_time_days"])
                            late = rng.random() < float(vendor["late_rate"])
                            actual_lead = lead + (rng.randint(1, 2) if late else 0)
                            arrive = d + timedelta(days=actual_lead)
                            received = qty
                            if rng.random() < float(vendor["partial_rate"]):
                                received = max(
                                    pack,
                                    _round_case(qty * rng.uniform(0.7, 0.95), pack),
                                )
                                received = min(received, qty)
                            in_transit[key].append((arrive, int(received)))
                        continue
                    disposition, risk, blocked_reason = _assign_historical_disposition(
                        rng=rng,
                        store=store,
                        product=product,
                        d=d,
                        oh=oh,
                        dos=dos,
                        ads=ads,
                        qty=qty,
                        pack=pack,
                        stockout_risk=stockout_risk,
                        low_cover=low_cover,
                        overstock=overstock,
                        large_order=large_order,
                        cover_target=cover_target,
                        trail=trail,
                        vendor=vendor,
                    )
                    if stockout_risk and qty == 0:
                        qty = pack
                    if (
                        disposition == "human_review"
                        and overstock
                        and not stockout_risk
                        and qty > 0
                    ):
                        qty = _round_case(max(pack, qty * 0.4), pack)
                    if disposition == "auto_release" and qty == 0:
                        disposition = "no_order"
                        risk = "balanced"

                decision_counter += 1
                run_decisions += 1
                rec_id = f"REC-HIST-{history_seed:04d}-{decision_counter:05d}"
                agent_qty = int(qty)
                forecast_units = round(ads * 7, 2)

                # Human outcome
                human_action = None
                final_qty = agent_qty
                if disposition == "auto_release":
                    human_action = "agent_approved"
                    final_qty = agent_qty
                elif disposition == "no_order":
                    human_action = "no_order"
                    final_qty = 0
                elif disposition == "blocked":
                    human_action = "blocked"
                    final_qty = 0
                elif disposition == "human_review":
                    override_bias = 0.12 + float(store.get("volatility", 0.1)) * 0.12
                    if product["sku"] in HIGH_OVERRIDE_SKUS:
                        override_bias = 0.34
                    if product["sku"] in LOW_OVERRIDE_SKUS:
                        override_bias = 0.05
                    if product["profile"] == "volatile":
                        override_bias += 0.06
                    r2 = rng.random()
                    if r2 < 0.1:
                        human_action = "rejected"
                        final_qty = 0
                    elif r2 < 0.1 + override_bias:
                        human_action = "adjusted"
                        direction = -1 if rng.random() < 0.55 else 1
                        delta_cases = rng.choice([1, 1, 2, 2, 3])
                        final_qty = max(0, agent_qty + direction * delta_cases * pack)
                        final_qty = _round_case(final_qty, pack)
                        if final_qty == agent_qty:
                            final_qty = max(0, agent_qty - pack)
                    else:
                        human_action = "approved"
                        final_qty = agent_qty

                created_at = datetime(
                    d.year, d.month, d.day, 8 + rng.randint(0, 6), rng.randint(0, 59), tzinfo=timezone.utc
                )
                vendor = VENDOR_BY_ID[product["vendor_id"]]
                lead = int(vendor["lead_time_days"])
                late = rng.random() < float(vendor["late_rate"])
                partial = rng.random() < float(vendor["partial_rate"])
                actual_lead = lead + (rng.randint(1, 3) if late else 0)
                ordered_qty = final_qty
                received_qty = ordered_qty
                if partial and ordered_qty > 0:
                    received_qty = max(pack, _round_case(ordered_qty * rng.uniform(0.6, 0.9), pack))
                    received_qty = min(received_qty, ordered_qty)

                decisions.append(
                    {
                        "recommendation_id": rec_id,
                        "run_id": run_id,
                        "store_id": store["store_id"],
                        "sku": product["sku"],
                        "product_name": product["product_name"],
                        "created_at": created_at,
                        "disposition": disposition,
                        "risk_level": risk,
                        "agent_qty": agent_qty,
                        "final_qty": final_qty,
                        "forecast_units": forecast_units,
                        "ads": round(ads, 3),
                        "dos": round(dos, 2),
                        "on_hand": int(round(oh)),
                        "in_transit": int(pending),
                        "safety": int(safety),
                        "case_pack": pack,
                        "human_action": human_action,
                        "vendor_id": product["vendor_id"],
                        "vendor_name": vendor["vendor_name"],
                        "unit_cost": float(product["unit_cost"]),
                        "ordered_qty": ordered_qty,
                        "received_qty": received_qty,
                        "lead_time_days": lead,
                        "actual_lead_days": actual_lead,
                        "late": late,
                        "partial": partial,
                        "blocked_reason": blocked_reason,
                    }
                )

                if ordered_qty > 0 and human_action in {
                    "agent_approved",
                    "approved",
                    "adjusted",
                }:
                    arrive = d + timedelta(days=actual_lead)
                    in_transit[key].append((arrive, int(received_qty)))
                    orders.append(
                        {
                            "recommendation_id": rec_id,
                            "store_id": key[0],
                            "sku": key[1],
                            "qty": ordered_qty,
                            "received_qty": received_qty,
                            "created_at": created_at + timedelta(hours=1),
                            "arrive": arrive,
                            "vendor_name": vendor["vendor_name"],
                            "unit_cost": float(product["unit_cost"]),
                            "late": late,
                            "partial": partial,
                            "lead_time_days": lead,
                            "actual_lead_days": actual_lead,
                            "released_by_type": (
                                "agent_policy"
                                if human_action == "agent_approved"
                                else "human"
                            ),
                        }
                    )

        _ = run_decisions

    # Ending inventory snapshot
    inventory_rows: list[dict[str, Any]] = []
    for store in STORES:
        for product in PRODUCTS:
            key = (store["store_id"], product["sku"])
            pending = sum(q for _, q in in_transit.get(key, []))
            oh = int(round(on_hand.get(key, 0)))
            # Preserve demo scenario ending positions
            preserved = PRESERVED_INVENTORY.get(key)
            if preserved:
                oh = preserved["on_hand"]
                pending = preserved["in_transit"]
            inventory_rows.append(
                {
                    "store_id": store["store_id"],
                    "store_name": store["store_name"],
                    "sku": product["sku"],
                    "on_hand": max(0, oh),
                    "in_transit": max(0, int(pending)),
                    "reserved": 0,
                    "updated_at": f"{_as_of().isoformat()}T06:00:00+00:00",
                }
            )
    return inventory_rows, decisions, orders, daily_rows


def write_master_csvs(
    *,
    data_dir: Path | None = None,
    seed: int | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Write products.csv, inventory.csv, sales.csv, inventory_daily.csv (deterministic)."""
    root = Path(data_dir or DATA_DIR)
    root.mkdir(parents=True, exist_ok=True)
    history_seed = resolve_history_seed(seed, data_dir=root)
    rng = rng or random.Random(history_seed)

    products_df = pd.DataFrame(
        [
            {
                "sku": p["sku"],
                "product_name": p["product_name"],
                "category": p["category"],
                "vendor_id": p["vendor_id"],
                "vendor_name": VENDOR_BY_ID[p["vendor_id"]]["vendor_name"],
                "case_pack_size": p["case_pack_size"],
                "safety_stock_units": p["safety_stock_units"],
                "unit_cost": p["unit_cost"],
                "retail_price": product_retail_price(p),
                "minimum_order_quantity": p["case_pack_size"],
                "maximum_order_quantity": max(240, p["case_pack_size"] * 40),
            }
            for p in PRODUCTS
        ]
    )
    built = build_history(rng=rng, history_seed=history_seed)
    sales_df = pd.DataFrame(built["sales_rows"])
    inventory_df = pd.DataFrame(built["inventory_rows"])
    daily_df = pd.DataFrame(built["daily_rows"])
    outcome_summary = summarize_decision_outcomes(built["decisions"])
    meta_path = write_history_meta(
        seed=history_seed,
        outcome_summary=outcome_summary,
        data_dir=root,
    )

    products_path = root / "products.csv"
    inventory_path = root / "inventory.csv"
    sales_path = root / "sales.csv"
    daily_path = root / "inventory_daily.csv"
    products_df.to_csv(products_path, index=False)
    inventory_df.to_csv(inventory_path, index=False)
    sales_df.to_csv(sales_path, index=False)
    daily_df.to_csv(daily_path, index=False)
    csv_repository.clear_csv_cache()

    return {
        "seed": history_seed,
        "meta_path": meta_path,
        "outcome_summary": outcome_summary,
        "products_path": str(products_path),
        "inventory_path": str(inventory_path),
        "sales_path": str(sales_path),
        "inventory_daily_path": str(daily_path),
        "stockout_days": int(daily_df["is_stockout"].sum()) if not daily_df.empty else 0,
        "stores": len(STORES),
        "skus": len(PRODUCTS),
        "vendors": len(VENDORS),
        "sales_rows": len(built["sales_rows"]),
        "decision_count": len(built["decisions"]),
        "order_count": len(built["orders"]),
        "history_days": HISTORY_DAYS,
    }


def build_history(
    *,
    rng: random.Random | None = None,
    history_seed: int | None = None,
) -> dict[str, Any]:
    """Deterministic sales + inventory evolution + decision/order specs."""
    history_seed = history_seed if history_seed is not None else DEMO_HISTORY_SEED
    rng = rng or random.Random(history_seed)
    sales_rows = generate_sales_rows(rng)
    inventory_rows, decisions, orders, daily_rows = _simulate_inventory_and_decisions(
        sales_rows, rng, history_seed=history_seed
    )
    return {
        "seed": history_seed,
        "sales_rows": sales_rows,
        "inventory_rows": inventory_rows,
        "decisions": decisions,
        "orders": orders,
        "daily_rows": daily_rows,
        "outcome_summary": summarize_decision_outcomes(decisions),
    }


def seed_historical_workflow(
    *,
    data_dir: Path | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Insert historical recommendations / reviews / intents / runs (deterministic)."""
    root = Path(data_dir or DATA_DIR)
    history_seed = resolve_history_seed(seed, data_dir=root)
    built = build_history(rng=random.Random(history_seed), history_seed=history_seed)
    decisions: list[dict[str, Any]] = built["decisions"]
    orders: list[dict[str, Any]] = built["orders"]
    orders_by_rec = {o["recommendation_id"]: o for o in orders}
    generated_summary = built["outcome_summary"]

    init_db()
    outcome_counts: dict[str, int] = {
        "auto_release": 0,
        "human_review": 0,
        "blocked": 0,
        "no_order": 0,
        "agent_approved": 0,
        "human_approved": 0,
        "human_adjusted": 0,
        "rejected": 0,
    }
    runs: dict[str, dict[str, Any]] = {}

    with get_session() as session:
        for d in decisions:
            disposition = d["disposition"]
            outcome_counts[disposition] = outcome_counts.get(disposition, 0) + 1
            human_action = d.get("human_action")
            if human_action == "agent_approved":
                outcome_counts["agent_approved"] += 1
                status = "approved"
            elif human_action == "approved":
                outcome_counts["human_approved"] += 1
                status = "approved"
            elif human_action == "adjusted":
                outcome_counts["human_adjusted"] += 1
                status = "approved"
            elif human_action == "rejected":
                outcome_counts["rejected"] += 1
                status = "rejected"
            elif disposition == "blocked":
                status = "blocked"
            elif disposition == "no_order":
                status = "no_order"
            else:
                status = "pending_review"

            created_at = pd.Timestamp(d["created_at"]).to_pydatetime()
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            run_id = d["run_id"]
            slot = runs.setdefault(
                run_id,
                {
                    "started_at": created_at,
                    "completed_at": created_at,
                    "total": 0,
                    "auto": 0,
                    "review": 0,
                    "blocked": 0,
                    "no_order": 0,
                },
            )
            slot["total"] += 1
            slot["completed_at"] = max(slot["completed_at"], created_at)
            if disposition == "auto_release":
                slot["auto"] += 1
            elif disposition == "human_review":
                slot["review"] += 1
            elif disposition == "blocked":
                slot["blocked"] += 1
            elif disposition == "no_order":
                slot["no_order"] += 1

            rec = RecommendationRow(
                recommendation_id=d["recommendation_id"],
                store_id=d["store_id"],
                sku=d["sku"],
                forecast_units=float(d["forecast_units"]),
                available_units=int(d["on_hand"]) + int(d["in_transit"]),
                agent_recommended_quantity=int(d["agent_qty"]),
                risk_level=d["risk_level"],
                rationale=(
                    f"Historical demo recommendation for {d['product_name']} "
                    f"at {d['store_id']} ({disposition})."
                ),
                created_at=created_at.replace(tzinfo=None),
                status=status,
                disposition=disposition,
                policy_id="policy-demo",
                policy_version="v1",
                policy_evaluation_json=json.dumps(
                    {
                        "disposition": disposition,
                        "seed": history_seed,
                        "blocked_reason": d.get("blocked_reason")
                        or (
                            "Stale or incomplete inventory signal"
                            if disposition == "blocked"
                            else None
                        ),
                    }
                ),
                product_name=d["product_name"],
                usable_on_hand=int(d["on_hand"]),
                in_transit=int(d["in_transit"]),
                safety_stock=int(d["safety"]),
                days_of_supply=float(d["dos"]),
                raw_quantity=float(d["agent_qty"]),
                case_pack=int(d["case_pack"]),
                average_daily_sales=float(d["ads"]),
                run_id=run_id,
                payload_json=json.dumps(
                    {
                        "seed": history_seed,
                        "vendor_id": d["vendor_id"],
                        "vendor": d["vendor_name"],
                        "unit_cost": d["unit_cost"],
                        "evidence": {
                            "vendor": d["vendor_name"],
                            "supplier_lead_time_days": d["lead_time_days"],
                            "unit_cost": d["unit_cost"],
                        },
                    }
                ),
                recommendation_version=1,
                user_id="demo_history",
                session_id="sess-demo-history",
            )
            session.add(rec)

            item_id = f"RITEM-{d['recommendation_id'][-8:]}"
            session.add(
                ReplenishmentRunItemRow(
                    item_id=item_id,
                    run_id=run_id,
                    store_id=d["store_id"],
                    sku=d["sku"],
                    status="scored",
                    disposition=disposition,
                    recommendation_id=d["recommendation_id"],
                    error_message=(
                        d.get("blocked_reason") or "Insufficient/stale inventory data"
                        if disposition == "blocked"
                        else None
                    ),
                    created_at=created_at.replace(tzinfo=None),
                    updated_at=created_at.replace(tzinfo=None),
                )
            )

            if human_action in {"approved", "adjusted", "rejected"}:
                agent_qty = int(d["agent_qty"])
                human_qty = int(d["final_qty"])
                diff = human_qty - agent_qty
                pct = (diff / agent_qty * 100.0) if agent_qty else 0.0
                review_id = f"REV-{d['recommendation_id'][-10:]}"
                action = (
                    "decline"
                    if human_action == "rejected"
                    else ("adjust" if human_action == "adjusted" else "approve")
                )
                session.add(
                    HumanReviewRow(
                        review_id=review_id,
                        recommendation_id=d["recommendation_id"],
                        agent_recommended_quantity=agent_qty,
                        human_proposed_quantity=human_qty,
                        override_used=human_action == "adjusted",
                        override_reason=(
                            "Historical override for demo analytics"
                            if human_action == "adjusted"
                            else None
                        ),
                        reason_code=(
                            "demand_change"
                            if human_action == "adjusted"
                            else ("not_needed" if human_action == "rejected" else "agree")
                        ),
                        comments=None,
                        decision_action=action,
                        quantity_source=(
                            "human" if human_action == "adjusted" else "agent"
                        ),
                        ai_recommendation_unavailable=False,
                        difference_units=diff,
                        difference_percent=float(pct),
                        projected_days_of_supply=float(d["dos"]),
                        projected_risk=d["risk_level"],
                        requires_escalation=False,
                        submitted_by="alex.store",
                        submitted_at=(created_at + timedelta(hours=2)).replace(tzinfo=None),
                        status="submitted",
                        approval_level="normal",
                        validation_messages_json="[]",
                        case_pack_compliant=True,
                        user_id="alex.store",
                        session_id="sess-demo-history",
                    )
                )

            order = orders_by_rec.get(d["recommendation_id"])
            if order:
                qty = int(order["qty"])
                unit_cost = float(order["unit_cost"])
                amount = round(qty * unit_cost, 2)
                intent_id = f"OI-{d['recommendation_id'][-10:]}"
                po_id = f"PO-{d['recommendation_id'][-10:]}"
                created = pd.Timestamp(order["created_at"]).to_pydatetime()
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                transmitted = created + timedelta(hours=1)
                acknowledged = transmitted + timedelta(days=int(order["actual_lead_days"]))
                lines = [
                    {
                        "line_number": 1,
                        "sku": order["sku"],
                        "store_id": order["store_id"],
                        "product_name": PRODUCT_BY_SKU[order["sku"]]["product_name"],
                        "quantity": qty,
                        "unit_cost": unit_cost,
                        "line_amount": amount,
                    }
                ]
                payload = {
                    "seed": history_seed,
                    "received_quantity": order["received_qty"],
                    "ordered_quantity": qty,
                    "fill_rate": (
                        round(order["received_qty"] / qty, 3) if qty else 1.0
                    ),
                    "late": order["late"],
                    "partial": order["partial"],
                    "lead_time_days": order["lead_time_days"],
                    "actual_lead_days": order["actual_lead_days"],
                }
                session.add(
                    OrderIntentRow(
                        order_intent_id=intent_id,
                        recommendation_id=d["recommendation_id"],
                        approval_id=None,
                        purchase_order_id=po_id,
                        status="acknowledged",
                        store_id=order["store_id"],
                        sku=order["sku"],
                        product_name=PRODUCT_BY_SKU[order["sku"]]["product_name"],
                        quantity=qty,
                        unit_cost=unit_cost,
                        amount=amount,
                        vendor=order["vendor_name"],
                        lines_json=json.dumps(lines),
                        source_run_id=run_id,
                        approved_by=(
                            "agent"
                            if order["released_by_type"] == "agent_policy"
                            else "alex.store"
                        ),
                        released_by_type=order["released_by_type"],
                        released_by_label=(
                            "Agent — Within Policy"
                            if order["released_by_type"] == "agent_policy"
                            else "Human — Store Manager"
                        ),
                        idempotency_key=f"hist-{intent_id}",
                        transmission_idempotency_key=f"tx-{intent_id}",
                        mock_erp_reference=f"ERP-{intent_id}",
                        external_order_id=f"EXT-{intent_id}",
                        erp_provider="mock",
                        transmitted_at=transmitted.replace(tzinfo=None),
                        acknowledged_at=acknowledged.replace(tzinfo=None),
                        last_error=None,
                        last_error_code=None,
                        last_error_message=None,
                        attempts=1,
                        last_attempt_at=transmitted.replace(tzinfo=None),
                        next_retry_at=None,
                        execution_id=None,
                        created_at=created.replace(tzinfo=None),
                        updated_at=acknowledged.replace(tzinfo=None),
                        user_id="demo_history",
                        session_id="sess-demo-history",
                        payload_json=json.dumps(payload),
                    )
                )
                session.add(
                    PurchaseOrderRow(
                        purchase_order_id=po_id,
                        approval_id=f"APPR-AUTO-{d['recommendation_id'][-8:]}",
                        recommendation_id=d["recommendation_id"],
                        store_id=order["store_id"],
                        sku=order["sku"],
                        agent_recommended_quantity=int(d["agent_qty"]),
                        human_proposed_quantity=int(d["final_qty"]),
                        approved_final_quantity=qty,
                        override_used=human_action == "adjusted",
                        override_reason=(
                            "Historical override" if human_action == "adjusted" else None
                        ),
                        status="acknowledged",
                        order_status="acknowledged",
                        transmission_status="acked",
                        created_at=created.replace(tzinfo=None),
                        transmitted_at=transmitted.replace(tzinfo=None),
                        acknowledged_at=acknowledged.replace(tzinfo=None),
                        vendor=order["vendor_name"],
                        amount=amount,
                        lines_json=json.dumps(lines),
                        source_run_id=run_id,
                        approved_by=(
                            "agent"
                            if order["released_by_type"] == "agent_policy"
                            else "alex.store"
                        ),
                        idempotency_key=f"po-hist-{po_id}",
                        user_id="demo_history",
                        session_id="sess-demo-history",
                    )
                )

        for run_id, meta in runs.items():
            session.add(
                ReplenishmentRunRow(
                    run_id=run_id,
                    started_at=meta["started_at"].replace(tzinfo=None),
                    completed_at=meta["completed_at"].replace(tzinfo=None),
                    status="completed",
                    trigger_type="scheduled",
                    initiated_by="demo_history",
                    total_items=meta["total"],
                    scored_items=meta["total"],
                    auto_released_items=meta["auto"],
                    review_items=meta["review"],
                    blocked_items=meta["blocked"],
                    no_order_items=meta["no_order"],
                    failed_items=0,
                    policy_version="v1",
                    model_name="demo-history",
                    error_summary=None,
                    created_at=meta["started_at"].replace(tzinfo=None),
                    invocation_key=f"hist:{run_id}",
                    scheduled_for=meta["started_at"].replace(tzinfo=None),
                )
            )

    db_summary = _query_db_outcome_counts()
    return {
        "status": "seeded_history",
        "seed": history_seed,
        "decision_count": len(decisions),
        "order_count": len(orders),
        "run_count": len(runs),
        "outcome_counts": outcome_counts,
        "generated_outcome_summary": generated_summary,
        "database_outcome_summary": db_summary,
        "stores": len(STORES),
        "skus": len(PRODUCTS),
        "vendors": len(VENDORS),
        "history_days": HISTORY_DAYS,
        "sales_rows": len(built["sales_rows"]),
    }


def regenerate_all(*, data_dir: Path | None = None, seed: int | None = None) -> dict[str, Any]:
    """Rewrite CSVs + return stats (DB seeding is separate via demo_data_service)."""
    result = write_master_csvs(data_dir=data_dir, seed=seed)
    print_outcome_summary(
        result["outcome_summary"],
        title=f"Generated demo history (seed={result['seed']})",
    )
    return result

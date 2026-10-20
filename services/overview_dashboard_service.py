"""Overview dashboard presentation read model.

Composes queue / order / greeting data for the landing experience.
No replenishment math, policy, ERP, or RBAC semantics live here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services import (
    morning_brief_service,
    purchase_order_service,
    queue_service,
)
from services import order_lifecycle_states as ols


def _confidence_display(value: object) -> str:
    if value is None:
        return "Not scored"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "Not scored"
    if n <= 1.0:
        return f"{n * 100:.0f}%"
    return f"{n:.0f}%"


def _fmt_dos(value: object) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
        text = f"{n:.1f}".rstrip("0").rstrip(".")
        return f"{text}d"
    except (TypeError, ValueError):
        return str(value)


def _fmt_qty(value: object) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
        if n.is_integer():
            return str(int(n))
        return f"{n:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _parse_datetime(raw: object) -> datetime | None:
    if raw is None or raw == "" or raw == "—":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00").replace(" ", "T")[:19])
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fmt_date_display(raw: object) -> str | None:
    """Human date label from persisted timestamps — never invents a date."""
    parsed = _parse_datetime(raw)
    if parsed is None:
        return None
    return parsed.strftime("%b %d, %Y").replace(" 0", " ")


def _first_line(order: dict[str, Any]) -> dict[str, Any]:
    lines = order.get("lines") or []
    return lines[0] if lines and isinstance(lines[0], dict) else {}


def _resolve_delivery_quantity(order: dict[str, Any]) -> object:
    line = _first_line(order)
    for key in (
        "approved_final_quantity",
        "quantity",
        "qty",
        "ordered_quantity",
    ):
        if order.get(key) is not None:
            return order.get(key)
    if line.get("quantity") is not None:
        return line.get("quantity")
    return None


def _resolve_delivery_product_name(order: dict[str, Any]) -> str:
    """Prefer persisted product name / master data — never use SKU as the name."""
    line = _first_line(order)
    sku = str(order.get("sku") or line.get("sku") or "").strip()
    candidates = [
        order.get("product_name"),
        line.get("product_name"),
        line.get("item"),
        order.get("product"),
    ]
    for name in candidates:
        text = str(name or "").strip()
        if text and text != "—" and text != sku:
            return text
    if sku:
        try:
            from services import product_service

            product = product_service.get_product_details(sku)
            if product.product_name:
                return str(product.product_name)
        except Exception:  # noqa: BLE001 — display fallback only
            pass
    return "—"


def _resolve_lead_time_days(order: dict[str, Any]) -> int | None:
    for key in ("lead_time_days", "supplier_lead_time_days", "expected_lead_time_days"):
        raw = order.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    sku = order.get("sku") or _first_line(order).get("sku")
    if not sku:
        return None
    try:
        from integrations.factory import get_supplier_provider
        from services import product_service

        vendor_id = None
        try:
            record = product_service.get_product_record(str(sku))
            vendor_id = record.get("vendor_id")
        except Exception:  # noqa: BLE001
            vendor_id = None
        if not vendor_id:
            return None
        lead = get_supplier_provider().get_expected_lead_time(str(vendor_id), sku=str(sku))
        return int(lead) if lead is not None else None
    except Exception:  # noqa: BLE001
        return None


def _resolve_expected_arrival_raw(order: dict[str, Any]) -> object:
    """Pick a supported ETA source only — never invent dates."""
    if order.get("expected_arrival"):
        return order.get("expected_arrival")
    if order.get("acknowledged_at"):
        return order.get("acknowledged_at")
    transmitted = order.get("transmitted_at")
    lead = _resolve_lead_time_days(order)
    parsed = _parse_datetime(transmitted)
    if parsed is not None and lead is not None:
        from datetime import timedelta

        return parsed + timedelta(days=int(lead))
    return None


def _resolve_shipment_status(order: dict[str, Any]) -> str:
    """Map persisted order timestamps/status to the 3 visual delivery stages."""
    return _delivery_stage_label(_delivery_stage_key(order))


def _delivery_stage_key(order: dict[str, Any]) -> str:
    raw = str(order.get("order_status") or order.get("status") or "").strip().lower()
    status = ols.normalize_status(raw)
    if (
        order.get("acknowledged_at")
        or status in {ols.ERP_ACKNOWLEDGED, ols.COMPLETED}
        or raw in {ols.ACKNOWLEDGED, ols.RECEIVED, "delivered"}
    ):
        return "delivered"
    if (
        order.get("transmitted_at")
        or status == ols.TRANSMITTING
        or raw in {ols.IN_TRANSIT, "sending"}
    ):
        return "in_transit"
    return "order_placed"


def _delivery_stage_label(stage: str) -> str:
    return {
        "order_placed": "Order Placed",
        "in_transit": "In Transit",
        "delivered": "Delivered",
    }.get(stage, "Order Placed")


def _delivery_stage_dates(order: dict[str, Any]) -> dict[str, str]:
    """Dates under tracker stages — only from persisted fields."""
    return {
        "order_placed": _fmt_date_display(order.get("created_at")) or "—",
        "in_transit": _fmt_date_display(order.get("transmitted_at")) or "—",
        "delivered": _fmt_date_display(order.get("acknowledged_at")) or "—",
    }


def _resolve_unit_cost(order: dict[str, Any]) -> object:
    line = _first_line(order)
    if line.get("unit_cost") is not None:
        return line.get("unit_cost")
    if order.get("unit_cost") is not None:
        return order.get("unit_cost")
    return None


def _resolve_order_total(order: dict[str, Any]) -> object:
    if order.get("amount") is not None:
        return order.get("amount")
    if order.get("value") is not None:
        return order.get("value")
    line = _first_line(order)
    if line.get("line_amount") is not None:
        return line.get("line_amount")
    qty = _resolve_delivery_quantity(order)
    unit = _resolve_unit_cost(order)
    if qty is not None and unit is not None:
        try:
            return round(float(qty) * float(unit), 2)
        except (TypeError, ValueError):
            return None
    return None


def _fmt_money(value: object) -> str:
    if value is None or value == "—":
        return "—"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _business_status(row: dict[str, Any]) -> str:
    disp = row.get("disposition") or ""
    if disp == "human_review" and row.get("open_for_decision"):
        return "Needs review"
    if disp == "blocked":
        return "Blocked"
    if disp == "auto_release":
        return "Handled automatically"
    if disp == "no_order":
        return "No order"
    return str(row.get("status") or disp or "—").replace("_", " ").title()


def _human_intervention_reason(row: dict[str, Any]) -> str:
    """Why a human must act — distinct from the inventory/business exception label."""
    from services.queue_service import why_needs_attention

    failed = list(row.get("failed_rules") or [])
    # Prefer explicit policy / threshold rules over inventory condition phrasing.
    if "auto_release_max_value" in failed:
        return "Order quantity exceeds autonomous approval threshold"
    if "formal_approval_value" in failed:
        return "Order value requires formal approval"
    if "minimum_confidence" in failed:
        return "Confidence is below the review threshold"
    if "stockout_review" in failed:
        return "Policy requires human approval for stockout risk"
    if "promotion_overlap" in failed:
        return "Promotion overlap requires review"
    if "maximum_days_of_supply" in failed:
        return "Days of supply exceeds the overstock threshold"
    if "supplier_constraint" in failed:
        return "Supplier constraint requires review"
    return why_needs_attention(
        disposition=row.get("disposition"),
        risk_level=row.get("risk_level"),
        failed_rules=failed,
    )


def _enrich_decision_row(row: dict[str, Any]) -> dict[str, Any]:
    qty = row.get("agent_quantity")
    withheld = row.get("disposition") == "blocked" or qty is None
    review_reason = ""
    if row.get("disposition") == "human_review" and row.get("open_for_decision"):
        review_reason = _human_intervention_reason(row)
    return {
        **row,
        "on_hand": row.get("usable_on_hand"),
        "on_hand_display": _fmt_qty(row.get("usable_on_hand")),
        "in_transit": row.get("in_transit"),
        "in_transit_display": _fmt_qty(row.get("in_transit")),
        "safety_stock_display": _fmt_qty(row.get("safety_stock")),
        "demand_7d_display": _fmt_qty(row.get("forecast_units")),
        "days_of_supply_display": _fmt_dos(row.get("days_of_supply")),
        "agent_qty_display": "Withheld" if withheld and row.get("disposition") == "blocked" else _fmt_qty(qty),
        "confidence_display": _confidence_display(row.get("confidence")),
        "business_status": _business_status(row),
        "why_review": review_reason or row.get("why") or row.get("exception") or "Needs judgment",
        "review_reason": review_reason,
    }


def _tile_secondary_needs(rows: list[dict[str, Any]]) -> str:
    stockout = sum(
        1
        for r in rows
        if (r.get("risk_level") == "stockout")
        or "stockout" in str(r.get("exception") or "").lower()
    )
    if stockout:
        return f"{stockout} have stockout risk"
    if not rows:
        return "No recommendations waiting"
    return "Human decision required"


def _tile_secondary_blocked(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No blocked recommendations"
    reasons = []
    for r in rows:
        exc = str(r.get("exception") or r.get("why") or "")
        if exc and exc not in reasons:
            reasons.append(exc)
        if len(reasons) >= 1:
            break
    return reasons[0] if reasons else "Recommendation withheld"


def _is_expected_delivery(order: dict[str, Any]) -> bool:
    """True inbound / expected POs only — not draft or ready-to-send queue rows."""
    status = ols.normalize_status(order.get("order_status") or order.get("status"))
    return status in {
        ols.TRANSMITTING,
        ols.ERP_ACKNOWLEDGED,
        ols.COMPLETED,
    }


def _delivery_explanation(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return "No inbound deliveries are currently expected."
    n = len(orders)
    if n == 1:
        return "1 inbound purchase order is expected."
    return f"{n} inbound purchase orders are expected."


def _arrival_bucket(order: dict[str, Any], *, today: datetime) -> str:
    """Classify arrival urgency from available timestamps — never invent dates."""
    raw = _resolve_expected_arrival_raw(order)
    if raw is None:
        raw = (
            order.get("expected_or_submitted")
            or order.get("transmitted_at")
        )
    parsed = _parse_datetime(raw)
    if parsed is None:
        return "unknown"
    day = parsed.astimezone(timezone.utc).date()
    today_d = today.astimezone(timezone.utc).date()
    delta = (day - today_d).days
    if delta <= 0:
        return "today"
    if delta <= 3:
        return "soon"
    return "later"


def _enrich_delivery_row(order: dict[str, Any], *, today: datetime) -> dict[str, Any]:
    status = ols.normalize_status(order.get("order_status") or order.get("status"))
    bucket = _arrival_bucket(order, today=today)
    if status in {ols.TRANSMISSION_FAILED, ols.RETRY_PENDING, ols.ERP_REJECTED}:
        bucket = "delayed"
    eta_raw = _resolve_expected_arrival_raw(order)
    arrival_display = _fmt_date_display(eta_raw) or "ETA unavailable"
    qty = _resolve_delivery_quantity(order)
    product = _resolve_delivery_product_name(order)
    unit_cost = _resolve_unit_cost(order)
    total = _resolve_order_total(order)
    order_date = _fmt_date_display(order.get("created_at") or order.get("transmitted_at"))
    stage = _delivery_stage_key(order)
    stage_dates = _delivery_stage_dates(order)
    primary_date = arrival_display
    if stage == "delivered" and stage_dates["delivered"] != "—":
        primary_date = stage_dates["delivered"]
    elif stage == "in_transit" and stage_dates["in_transit"] != "—":
        primary_date = stage_dates["in_transit"]
    elif stage_dates["order_placed"] != "—":
        primary_date = stage_dates["order_placed"]
    return {
        **order,
        "arrival_bucket": bucket,
        "arrival_display": arrival_display,
        "expected_arrival_resolved": eta_raw,
        "status_label": order.get("order_status_label")
        or ols.format_lifecycle_label(status),
        "delivery_stage": stage,
        "delivery_stage_label": _delivery_stage_label(stage),
        "shipment_status": _delivery_stage_label(stage),
        "stage_dates": stage_dates,
        "primary_date_display": primary_date,
        "po_ref": order.get("purchase_order_id")
        or order.get("external_order_id")
        or order.get("mock_erp_reference")
        or order.get("order_intent_id")
        or "—",
        "supplier": order.get("vendor") or order.get("supplier") or "—",
        "product": product,
        "product_name": product if product != "—" else order.get("product_name"),
        "quantity": qty,
        "quantity_display": _fmt_qty(qty),
        "unit_cost": unit_cost,
        "unit_cost_display": _fmt_money(unit_cost),
        "order_total": total,
        "order_total_display": _fmt_money(total),
        "order_date_display": order_date or "—",
        "erp_reference": order.get("external_order_id")
        or order.get("mock_erp_reference")
        or order.get("erp_reference")
        or "—",
        "invoice_number": order.get("invoice_number") or "",
    }


def _expected_deliveries_payload(orders: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = []
    today_n = soon_n = delayed_n = 0
    for o in orders:
        if not _is_expected_delivery(o):
            continue
        enriched = _enrich_delivery_row(o, today=now)
        bucket = enriched.get("arrival_bucket")
        if bucket == "today":
            today_n += 1
        elif bucket == "soon":
            soon_n += 1
        elif bucket == "delayed":
            delayed_n += 1
        rows.append(enriched)

    secondary = (
        f"{today_n} arriving today"
        if today_n
        else (
            f"{soon_n} arriving soon"
            if soon_n
            else (
                f"{delayed_n} delayed / at risk"
                if delayed_n
                else "Orders accepted by the purchasing system"
            )
        )
    )
    if not rows:
        secondary = "No inbound deliveries are currently expected"
    # Stable priority: delayed → today → soon → later → unknown
    bucket_rank = {"delayed": 0, "today": 1, "soon": 2, "later": 3, "unknown": 4}
    rows.sort(key=lambda r: (bucket_rank.get(r.get("arrival_bucket"), 9), str(r.get("po_ref"))))
    return {
        "count": len(rows),
        "rows": rows,
        "arriving_today": today_n,
        "arriving_soon": soon_n,
        "delayed": delayed_n,
        "secondary": secondary,
        "explanation": _delivery_explanation(rows),
    }


def get_overview_dashboard(
    *,
    actor_role: str | None = None,
    display_name: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Full Overview landing read model from existing services."""
    del actor_role  # permissions applied in UI against auth_service
    queue = queue_service.get_todays_queue(filter_key="all")
    try:
        workbench = purchase_order_service.get_orders_workbench()
    except Exception:  # noqa: BLE001
        workbench = {"orders": [], "summary": {}}

    rows = [_enrich_decision_row(r) for r in (queue.get("rows") or [])]
    summary = queue.get("summary") or {}
    run = queue.get("run")
    has_run = run is not None

    needs_rows = [
        r
        for r in rows
        if r.get("disposition") == "human_review" and r.get("open_for_decision")
    ]
    blocked_rows = [r for r in rows if r.get("disposition") == "blocked"]
    auto_rows = [r for r in rows if r.get("disposition") == "auto_release"]
    no_order_rows = [r for r in rows if r.get("disposition") == "no_order"]
    automated_rows = auto_rows + no_order_rows

    needs_n = int(summary.get("needs_review") or len(needs_rows))
    blocked_n = int(summary.get("blocked") or len(blocked_rows))
    auto_n = int(summary.get("auto_released") or len(auto_rows))
    no_order_n = int(summary.get("no_order") or len(no_order_rows))
    # Card + filter "Handled automatically" = auto-released + no-order (matches detail page).
    handled_n = auto_n + no_order_n

    deliveries = _expected_deliveries_payload(list(workbench.get("orders") or []))

    if not has_run:
        data_state = "no_run"
    elif needs_n == 0 and blocked_n == 0 and handled_n == 0 and not rows:
        data_state = "empty_pipeline"
    elif needs_n == 0 and blocked_n == 0:
        data_state = "healthy_zero"
    else:
        data_state = "actionable"

    def _count_display(n: int) -> int:
        return int(n)

    tiles = [
        {
            "key": "needs_review",
            "label": "Needs your review",
            "value": _count_display(needs_n),
            "count": needs_n,
            "explanation": (
                "No recommendations need your review."
                if needs_n == 0
                else "Held by guardrail or confidence"
            ),
            "secondary": _tile_secondary_needs(needs_rows),
            "accent": "danger",
            "route": "pages/11_Needs_Review.py",
        },
        {
            "key": "blocked",
            "label": "Blocked",
            "value": _count_display(blocked_n),
            "count": blocked_n,
            "explanation": (
                "No recommendations are currently blocked."
                if blocked_n == 0
                else "Agent could not safely complete the recommendation"
            ),
            "secondary": _tile_secondary_blocked(blocked_rows),
            "accent": "amber",
            "route": "pages/12_Blocked.py",
        },
        {
            "key": "automated",
            "label": "Handled automatically",
            "value": _count_display(handled_n),
            "count": handled_n,
            "explanation": (
                "No decisions have been handled automatically yet."
                if handled_n == 0
                else "Inside policy limits or no order needed"
            ),
            "secondary": (
                "Waiting for the first completed review"
                if handled_n == 0
                else "No action needed"
            ),
            "accent": "success",
            "route": "pages/13_Handled_Automatically.py",
        },
        {
            "key": "deliveries",
            "label": "Expected deliveries",
            "value": _count_display(deliveries["count"]),
            "count": deliveries["count"],
            "explanation": (
                deliveries.get("explanation")
                or "No inbound deliveries are currently expected."
            ),
            "secondary": deliveries["secondary"],
            "accent": "info",
            "route": "pages/14_Expected_Deliveries.py",
        },
    ]

    prioritized = morning_brief_service.prioritize_rows(rows)
    if not prioritized:
        prioritized = sorted(
            rows,
            key=lambda r: (
                float(r["days_of_supply"])
                if r.get("days_of_supply") is not None
                else 999.0
            ),
        )

    greeting = morning_brief_service.contextual_greeting(display_name, now=now)

    return {
        "greeting": greeting,
        "subtitle": (
            "The agent is monitoring inventory across all locations and has identified "
            "the following replenishment decisions."
        ),
        "tiles": tiles,
        "summary": {
            "needs_review": needs_n,
            "blocked": blocked_n,
            "auto_released": auto_n,
            "no_order": no_order_n,
            "handled_automatically": handled_n,
            "expected_deliveries": deliveries["count"],
            "all": len(rows),
        },
        "rows": prioritized,
        "all_rows": rows,
        "needs_rows": needs_rows,
        "blocked_rows": blocked_rows,
        "automated_rows": automated_rows,
        "deliveries": deliveries,
        "has_run": has_run,
        "run": run,
        "data_state": data_state,
        "healthy_message": (
            "All monitored items are currently within policy."
            if data_state == "healthy_zero"
            else None
        ),
        "empty_table_message": (
            "No replenishment decisions yet"
            if data_state in {"no_run", "empty_pipeline"}
            else (
                "All monitored items are currently within policy."
                if data_state == "healthy_zero"
                else None
            )
        ),
        "empty_table_detail": (
            "Once the agent evaluates your inventory, decisions will appear here."
            if data_state in {"no_run", "empty_pipeline"}
            else None
        ),
        "chip_counts": {
            "all": len(rows),
            "needs_review": needs_n,
            "blocked": blocked_n,
            # Same universe as the Handled automatically card (auto_release + no_order).
            "auto_released": handled_n,
        },
    }


def _automated_why(row: dict[str, Any]) -> str:
    disp = row.get("disposition")
    if disp == "auto_release":
        return "Auto-released within policy — every applicable guardrail passed."
    if disp == "no_order":
        return "No-order because existing inventory is sufficient for expected demand."
    return str(row.get("why") or row.get("exception") or "Handled without human intervention")


def _blocked_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Business-facing block copy from persisted queue / policy evaluation fields."""
    from services.queue_service import resolve_blocked_detail

    evaluation: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    rid = row.get("recommendation_id")
    if rid:
        try:
            from services import recommendation_service

            rec = recommendation_service.get_recommendation(str(rid), check_access=False)
            evaluation = rec.get("policy_evaluation") or {}
            evidence = rec.get("evidence") or {}
        except Exception:  # noqa: BLE001
            pass
    return resolve_blocked_detail(
        row,
        policy_evaluation=evaluation,
        evidence=evidence,
    )


def get_tile_detail(tile_key: str) -> dict[str, Any]:
    """Detail payload for a dashboard tile drill-down."""
    dash = get_overview_dashboard()
    if tile_key == "needs_review":
        rows = dash["needs_rows"]
        total_qty = sum(float(r.get("agent_quantity") or 0) for r in rows)
        total_value = sum(float(r.get("order_value") or 0) for r in rows)
        breakdown: dict[str, int] = {}
        for r in rows:
            key = str(r.get("exception") or "Needs review")
            breakdown[key] = breakdown.get(key, 0) + 1
        return {
            "key": tile_key,
            "title": "Needs your review",
            "rows": rows,
            "total_items": len(rows),
            "total_qty": total_qty,
            "total_value": total_value,
            "total_value_display": f"${total_value:,.2f}",
            "breakdown": breakdown,
        }
    if tile_key == "blocked":
        rows = [{**r, **_blocked_fields(r)} for r in dash["blocked_rows"]]
        return {
            "key": tile_key,
            "title": "Blocked",
            "rows": rows,
            "total_items": len(rows),
        }
    if tile_key == "automated":
        rows = [
            {
                **r,
                "decision_label": (
                    "Auto-released within policy"
                    if r.get("disposition") == "auto_release"
                    else "No order — inventory sufficient"
                    if r.get("disposition") == "no_order"
                    else _business_status(r)
                ),
                "why_safe": _automated_why(r),
                "policy_outcome": _business_status(r),
            }
            for r in dash["automated_rows"]
        ]
        return {
            "key": tile_key,
            "title": "Handled automatically",
            "rows": rows,
            "total_items": len(rows),
        }
    if tile_key == "deliveries":
        return {
            "key": tile_key,
            "title": "Expected deliveries",
            **dash["deliveries"],
            "total_items": dash["deliveries"]["count"],
            "groups": {
                "Arriving today": [
                    r for r in dash["deliveries"]["rows"] if r.get("arrival_bucket") == "today"
                ],
                "Arriving soon": [
                    r for r in dash["deliveries"]["rows"] if r.get("arrival_bucket") == "soon"
                ],
                "Delayed / at risk": [
                    r
                    for r in dash["deliveries"]["rows"]
                    if r.get("arrival_bucket") == "delayed"
                ],
                "Other expected": [
                    r
                    for r in dash["deliveries"]["rows"]
                    if r.get("arrival_bucket") in {"later", "unknown"}
                ],
            },
        }
    raise ValueError(f"Unknown tile: {tile_key}")


def get_delivery_detail(purchase_order_id: str) -> dict[str, Any]:
    """Resolve delivery modal fields for one purchase order (display only)."""
    from database.connection import get_session
    from repositories import order_intent_repository
    from services import product_service
    from services.queue_service import format_order_status_label

    po_id = str(purchase_order_id or "").strip()
    if not po_id:
        return {"ok": False, "message": "Purchase order not found."}

    payload = purchase_order_service.get_purchase_order_status(po_id)
    if not payload or payload.get("status") == "not_found":
        return {"ok": False, "message": "Purchase order not found.", "purchase_order_id": po_id}

    status = payload.get("order_status") or payload.get("status")
    extras: dict[str, Any] = {
        "order_status_label": format_order_status_label(status),
    }
    invoice_number = ""
    recommendation_id = payload.get("recommendation_id")
    if recommendation_id:
        try:
            with get_session() as session:
                intent = order_intent_repository.get_by_recommendation(
                    session, str(recommendation_id)
                )
            if intent is not None:
                extras["external_order_id"] = (
                    payload.get("external_order_id")
                    or payload.get("erp_reference")
                    or intent.external_order_id
                    or intent.mock_erp_reference
                )
                if not payload.get("vendor") and intent.vendor:
                    extras["vendor"] = intent.vendor
                if not payload.get("product_name") and intent.product_name:
                    extras["product_name"] = intent.product_name
                if payload.get("acknowledged_at") is None and intent.acknowledged_at:
                    extras["acknowledged_at"] = intent.acknowledged_at.isoformat()
                if payload.get("transmitted_at") is None and intent.transmitted_at:
                    extras["transmitted_at"] = intent.transmitted_at.isoformat()
                payload_data = intent.payload or {}
                if isinstance(payload_data, dict):
                    invoice_number = str(payload_data.get("invoice_number") or "").strip()
        except Exception:  # noqa: BLE001 — modal still renders core PO fields
            pass

    enriched = _enrich_delivery_row(
        {**payload, **extras, "invoice_number": invoice_number},
        today=datetime.now(timezone.utc),
    )
    store_id = enriched.get("store_id")
    qty = enriched.get("quantity")
    qty_display = enriched.get("quantity_display") or "—"
    if qty is not None and qty_display != "—":
        try:
            n = float(qty)
            units = "unit" if abs(n - 1) < 1e-9 else "units"
            qty_display = f"{_fmt_qty(qty)} {units}"
        except (TypeError, ValueError):
            qty_display = str(qty)

    stage_dates = enriched.get("stage_dates") or {}
    return {
        "ok": True,
        "purchase_order_id": po_id,
        "po_ref": enriched.get("po_ref") or po_id,
        "supplier": enriched.get("supplier") or "—",
        "store_id": store_id,
        "store": product_service.store_display_name(store_id),
        "product": enriched.get("product") or "—",
        "sku": enriched.get("sku") or "—",
        "quantity": qty,
        "quantity_display": qty_display,
        "status_label": enriched.get("status_label") or "—",
        "delivery_stage": enriched.get("delivery_stage") or "order_placed",
        "delivery_stage_label": enriched.get("delivery_stage_label") or "Order Placed",
        "stage_dates": stage_dates,
        "primary_date_display": enriched.get("primary_date_display")
        or enriched.get("arrival_display")
        or "—",
        "expected_arrival": enriched.get("arrival_display") or "ETA unavailable",
        "erp_reference": enriched.get("erp_reference") or "—",
        "order_date": enriched.get("order_date_display") or "—",
        "shipment_status": enriched.get("shipment_status") or "—",
        "unit_cost_display": enriched.get("unit_cost_display") or "—",
        "order_total_display": enriched.get("order_total_display") or "—",
        "invoice_number": invoice_number,
    }


def get_item_sales_series(store_id: str, sku: str, *, days: int = 14) -> dict[str, Any]:
    """Recent sales for charts — via forecast_service / sales provider only."""
    from services import forecast_service

    try:
        frame = forecast_service.get_sales_trend(store_id, sku, days=days)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": "Not enough recent sales history to chart.",
            "error": str(exc),
            "points": [],
        }
    if frame is None or getattr(frame, "empty", True):
        return {
            "ok": False,
            "message": "Not enough recent sales history to chart.",
            "points": [],
        }
    points = [
        {
            "date": str(row["date"])[:10],
            "units_sold": float(row["units_sold"]),
        }
        for _, row in frame.iterrows()
    ]
    if len(points) < 2:
        return {
            "ok": False,
            "message": "Not enough recent sales history to chart.",
            "points": points,
        }
    return {"ok": True, "message": None, "points": points, "title": "Recent sales"}

"""Current inventory on hand — operational read model (not historical analytics)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from config import AS_OF_DATE, RISK_OVERSTOCK_DOS_THRESHOLD, RISK_STOCKOUT_DOS_THRESHOLD
from database.connection import get_session, init_db
from database.models import RecommendationRow
from integrations.factory import get_inventory_provider, get_product_provider
from repositories import csv_repository
from services import forecast_service, product_service, replenishment_service
from services.overview_dashboard_service import (
    _delivery_stage_key,
    _fmt_date_display,
    _parse_datetime,
    _resolve_delivery_quantity,
    _resolve_expected_arrival_raw,
)
from services.purchase_order_service import list_purchase_orders
from services.queue_service import _display_status, recommendation_language
from services.risk_service import assess_replenishment_risk

INVENTORY_STATUS_LABELS: dict[str, str] = {
    "stockout_risk": "Stockout Risk",
    "low_stock": "Low Stock",
    "healthy": "Healthy",
    "excess": "Excess",
    "incoming": "Incoming",
}

INVENTORY_STATUS_KINDS: dict[str, str] = {
    "stockout_risk": "critical",
    "low_stock": "attention",
    "healthy": "success",
    "excess": "warning",
    "incoming": "progress",
}

STATUS_SORT_ORDER: dict[str, int] = {
    "stockout_risk": 0,
    "low_stock": 1,
    "incoming": 2,
    "healthy": 3,
    "excess": 4,
}

DECISION_HEADLINE: dict[str, str] = {
    "auto_release": "Handled automatically",
    "human_review": "Needs review",
    "blocked": "Blocked",
    "no_order": "No order needed",
}


@dataclass(frozen=True)
class InventoryFilters:
    search: str = ""
    store_id: str | None = None
    vendor: str | None = None
    status: str = "all"


def _classify_inventory_status(
    *,
    usable_on_hand: int,
    in_transit: int,
    safety_stock: int,
    days_of_supply: Decimal | None,
    forecast_units: Decimal,
    recommended_quantity: int,
    method: str | None,
) -> str:
    """Map current position to display status using shared risk thresholds."""
    dos_on_hand = replenishment_service._days_of_supply(usable_on_hand, forecast_units)
    dos_with_inbound = replenishment_service._days_of_supply(
        usable_on_hand + in_transit, forecast_units
    )
    stockout_threshold = Decimal(str(RISK_STOCKOUT_DOS_THRESHOLD))
    overstock_threshold = Decimal(str(RISK_OVERSTOCK_DOS_THRESHOLD))

    if (
        in_transit > 0
        and dos_on_hand is not None
        and dos_with_inbound is not None
        and dos_on_hand < stockout_threshold
        and dos_with_inbound >= stockout_threshold
    ):
        return "incoming"

    risk = assess_replenishment_risk(
        days_of_supply=days_of_supply,
        recommended_quantity=recommended_quantity,
        forecast_units=forecast_units,
        on_hand=usable_on_hand,
        usable_on_hand=usable_on_hand,
        method=method,
    )
    risk_level = str(risk.get("risk_level") or "")

    if risk_level == "stockout":
        return "stockout_risk"

    if risk_level == "overstock" or (
        days_of_supply is not None and days_of_supply > overstock_threshold
    ):
        return "excess"

    if usable_on_hand <= safety_stock or (
        dos_on_hand is not None and dos_on_hand < stockout_threshold
    ):
        return "low_stock"

    return "healthy"


def _latest_recommendations() -> dict[tuple[str, str], RecommendationRow]:
    init_db()
    latest: dict[tuple[str, str], RecommendationRow] = {}
    with get_session() as session:
        stmt = select(RecommendationRow).order_by(RecommendationRow.created_at.desc())
        for rec in session.scalars(stmt):
            key = (str(rec.store_id), str(rec.sku))
            if key not in latest:
                latest[key] = rec
    return latest


def _inbound_delivery_index(orders: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for order in orders:
        if _delivery_stage_key(order) == "delivered":
            continue
        store_id = str(order.get("store_id") or "").strip()
        sku = str(order.get("sku") or "").strip()
        if not store_id or not sku:
            continue
        eta_raw = _resolve_expected_arrival_raw(order)
        eta_dt = _parse_datetime(eta_raw)
        qty = _resolve_delivery_quantity(order)
        try:
            qty_int = int(qty) if qty is not None else 0
        except (TypeError, ValueError):
            qty_int = 0
        if qty_int <= 0:
            continue
        key = (store_id, sku)
        existing = index.get(key)
        if existing is None:
            index[key] = {
                "quantity": qty_int,
                "eta_raw": eta_raw,
                "eta_dt": eta_dt,
                "purchase_order_id": order.get("purchase_order_id"),
            }
            continue
        existing_dt = existing.get("eta_dt")
        if eta_dt is not None and (existing_dt is None or eta_dt < existing_dt):
            index[key] = {
                "quantity": qty_int,
                "eta_raw": eta_raw,
                "eta_dt": eta_dt,
                "purchase_order_id": order.get("purchase_order_id"),
            }
    return index


def _decision_payload(rec: RecommendationRow | None) -> dict[str, Any] | None:
    if rec is None:
        return None
    disposition = rec.disposition or "human_review"
    workflow_status = rec.status or "pending_review"
    status_label, _ = _display_status(disposition, workflow_status)
    headline = DECISION_HEADLINE.get(disposition, status_label)
    qty_text = recommendation_language(
        disposition=disposition,
        agent_quantity=rec.agent_recommended_quantity,
        case_pack=getattr(rec, "case_pack", None),
        workflow_status=workflow_status,
    )
    created = rec.created_at
    created_display = None
    if created is not None:
        if isinstance(created, datetime):
            created_display = created.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
        else:
            created_display = _fmt_date_display(created)
    summary = headline
    if qty_text and qty_text not in {headline, "Review required"}:
        summary = f"{headline} · {qty_text}"
    return {
        "recommendation_id": rec.recommendation_id,
        "headline": headline,
        "quantity_text": qty_text,
        "summary": summary,
        "created_at": created_display,
        "disposition": disposition,
        "workflow_status": workflow_status,
    }


def build_inventory_on_hand_dataset() -> dict[str, Any]:
    """Load current inventory once and derive row-level operational fields."""
    inv_provider = get_inventory_provider()
    product_provider = get_product_provider()
    snapshot = inv_provider.get_inventory_snapshot()
    latest_recs = _latest_recommendations()
    inbound_index = _inbound_delivery_index(list_purchase_orders(limit=500))
    vendors: set[str] = set()
    rows: list[dict[str, Any]] = []

    for item in snapshot:
        position = item.position
        store_id = position.store_id
        sku = position.sku
        try:
            product_record = product_provider.get_product(sku)
        except Exception:  # noqa: BLE001
            continue
        if product_record is None:
            continue
        product_model = product_record.to_product()
        try:
            forecast = forecast_service.get_demand_forecast(store_id, sku, as_of_date=AS_OF_DATE)
        except Exception:  # noqa: BLE001
            continue
        repl = replenishment_service.calculate_replenishment(
            store_id=store_id,
            sku=sku,
            forecast_units=forecast.forecast_units,
            inventory=position,
            product=product_model,
        )
        status_key = _classify_inventory_status(
            usable_on_hand=position.usable_on_hand,
            in_transit=position.in_transit,
            safety_stock=position.safety_stock,
            days_of_supply=repl.days_of_supply,
            forecast_units=forecast.forecast_units,
            recommended_quantity=repl.recommended_quantity,
            method=forecast.method,
        )
        vendor_name = (
            getattr(product_model, "vendor_name", None)
            or getattr(product_record, "vendor_name", None)
            or ""
        )
        vendor_name = str(vendor_name).strip()
        if vendor_name:
            vendors.add(vendor_name)
        store_name = product_service.store_display_name(store_id)
        dos = repl.days_of_supply
        dos_display = f"{float(dos):.1f}" if dos is not None else "—"
        inbound = inbound_index.get((store_id, sku))
        next_delivery_display = "No inbound delivery scheduled"
        if inbound:
            eta_label = _fmt_date_display(inbound.get("eta_raw")) or "ETA unavailable"
            next_delivery_display = f"{int(inbound['quantity']):,} units · {eta_label}"
        rec = latest_recs.get((store_id, sku))
        rows.append(
            {
                "row_key": f"{store_id}|{sku}",
                "store_id": store_id,
                "sku": sku,
                "store_name": store_name,
                "product_name": product_model.product_name or sku,
                "vendor_name": vendor_name or "—",
                "on_hand": int(position.on_hand),
                "in_transit": int(position.in_transit),
                "safety_stock": int(position.safety_stock),
                "forecast_units": float(forecast.forecast_units),
                "days_of_supply": float(dos) if dos is not None else None,
                "days_of_supply_display": dos_display,
                "status_key": status_key,
                "status_label": INVENTORY_STATUS_LABELS[status_key],
                "status_kind": INVENTORY_STATUS_KINDS[status_key],
                "next_delivery_display": next_delivery_display,
                "decision": _decision_payload(rec),
            }
        )

    rows.sort(
        key=lambda r: (
            STATUS_SORT_ORDER.get(str(r["status_key"]), 99),
            r["days_of_supply"] if r["days_of_supply"] is not None else 9999.0,
            str(r["product_name"]),
        )
    )
    store_options = [
        {"store_id": row["store_id"], "store_name": row["store_name"]}
        for row in csv_repository.list_stores()
    ]
    return {
        "rows": rows,
        "vendors": sorted(vendors),
        "stores": store_options,
        "row_count": len(rows),
    }


def apply_inventory_filters(
    rows: list[dict[str, Any]], filters: InventoryFilters
) -> list[dict[str, Any]]:
    search = (filters.search or "").strip().lower()
    out: list[dict[str, Any]] = []
    for row in rows:
        if filters.store_id and row["store_id"] != filters.store_id:
            continue
        if filters.vendor and row.get("vendor_name") != filters.vendor:
            continue
        if filters.status != "all" and row.get("status_key") != filters.status:
            continue
        if search:
            hay = f"{row.get('product_name', '')} {row.get('sku', '')}".lower()
            if search not in hay:
                continue
        out.append(row)
    return out


def summarize_inventory_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "skus_in_scope": len(rows),
        "stockout_risk": 0,
        "low_stock": 0,
        "healthy": 0,
        "excess": 0,
        "units_in_transit": 0,
    }
    for row in rows:
        key = str(row.get("status_key") or "")
        if key == "stockout_risk":
            summary["stockout_risk"] += 1
        elif key == "low_stock":
            summary["low_stock"] += 1
        elif key == "healthy":
            summary["healthy"] += 1
        elif key == "excess":
            summary["excess"] += 1
        summary["units_in_transit"] += int(row.get("in_transit") or 0)
    return summary


def get_inventory_row_detail(
    rows: list[dict[str, Any]], row_key: str
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("row_key") == row_key:
            return row
    return None

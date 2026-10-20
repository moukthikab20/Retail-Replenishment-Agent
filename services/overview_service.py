"""Replenishment Overview read model — composes existing services only.

No scoring, policy, ERP, or workflow logic lives here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services import (
    auth_service,
    batch_run_service,
    ops_health_service,
    product_service,
    purchase_order_service,
    queue_service,
    scheduler_service,
)

# Presentation states for zero / pre-run experience (UI only).
FIRST_RUN_READY = "FIRST_RUN_READY"
WAITING_FOR_SCHEDULE = "WAITING_FOR_SCHEDULE"
RUNNING = "RUNNING"
MISSED_SCHEDULE = "MISSED_SCHEDULE"
FAILED = "FAILED"
DATA_NOT_READY = "DATA_NOT_READY"

_ZERO_KEYS = frozenset(
    {
        FIRST_RUN_READY,
        WAITING_FOR_SCHEDULE,
        RUNNING,
        MISSED_SCHEDULE,
        FAILED,
        DATA_NOT_READY,
    }
)


def _customer_feed_status(raw: str | None) -> str:
    value = (raw or "unknown").lower()
    if value in {"healthy", "ok"}:
        return "Ready"
    if value in {"stale", "degraded"}:
        return "Stale"
    if value in {"unavailable", "failed", "disabled"}:
        return "Unavailable"
    return "Unknown"


def _source_display(
    *,
    status: str,
    relative_age: str | None = None,
    connectivity_only: bool = False,
) -> tuple[str, str]:
    """
    Customer-facing status + detail line.

    READY = source available; FRESHNESS only when a genuine watermark exists.
    Connectivity-only providers use Connected (never a fabricated age).
    """
    if status == "Unavailable":
        return "Unavailable", "Unavailable"
    if status == "Stale":
        if relative_age:
            age = relative_age.replace("updated ", "last updated ")
            return "Stale", f"Stale · {age}"
        return "Stale", "Stale"
    if connectivity_only:
        return "Connected", "Connected"
    if relative_age:
        return "Ready", f"Ready · {relative_age}"
    return "Ready", "Ready"


def _build_data_sources(
    *,
    freshness: dict[str, Any],
    providers: dict[str, Any],
    erp_ok: bool,
) -> list[dict[str, Any]]:
    """Compose Overview data-source strip from feed freshness + provider health."""
    sources: list[dict[str, Any]] = []

    for key, label in (("inventory", "Inventory"), ("sales", "Sales")):
        block = freshness.get(key) or {}
        base = _customer_feed_status(block.get("status"))
        watermark = block.get("watermark")
        # Only use age when a real watermark exists (demo inventory may set age=0 without one).
        relative = None
        if watermark:
            if key == "sales" and block.get("age_days") is not None:
                relative = format_relative_age(age_days=float(block["age_days"]))
            elif block.get("age_hours") is not None:
                relative = format_relative_age(age_hours=float(block["age_hours"]))
            else:
                relative = format_relative_age(watermark=str(watermark))
        status, detail = _source_display(
            status=base,
            relative_age=relative,
            connectivity_only=False,
        )
        sources.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "display": detail,
                "kind": {
                    "Ready": "success",
                    "Connected": "success",
                    "Stale": "attention",
                    "Unavailable": "critical",
                }.get(status, "neutral"),
                "has_freshness": relative is not None,
            }
        )

    for key, label in (
        ("product", "Products"),
        ("supplier", "Suppliers"),
        ("erp", "Purchasing"),
    ):
        block = providers.get(key) or {}
        ok = block.get("ok", True) if "ok" in block else True
        if key == "erp":
            ok = erp_ok and ok
        base = "Ready" if ok else "Unavailable"
        status, detail = _source_display(
            status=base,
            relative_age=None,
            connectivity_only=True,
        )
        sources.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "detail": detail,
                "display": detail,
                "kind": "success" if status == "Connected" else "critical",
                "has_freshness": False,
            }
        )
    return sources


def _priority_label(row: dict[str, Any]) -> str:
    risk = row.get("risk_level") or ""
    if risk == "stockout":
        return "High"
    conf = row.get("confidence")
    if conf is not None:
        try:
            if float(conf) < 0.75:
                return "Medium"
        except (TypeError, ValueError):
            pass
    if risk == "overstock":
        return "Medium"
    return "Normal"


def _risk_label(risk: str | None) -> str:
    return {
        "stockout": "Stockout risk",
        "overstock": "Overstock risk",
        "balanced": "Balanced",
        "manual_review": "Needs judgment",
        "insufficient_data": "Insufficient data",
    }.get(risk or "", (risk or "—").replace("_", " ").title())


def format_relative_age(
    *,
    age_hours: float | None = None,
    age_days: float | None = None,
    watermark: str | None = None,
) -> str | None:
    """Human relative age from a genuine watermark/age — never invents time."""
    hours: float | None = None
    if age_hours is not None:
        hours = float(age_hours)
    elif age_days is not None:
        hours = float(age_days) * 24.0
    elif watermark:
        try:
            parsed = datetime.fromisoformat(str(watermark).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            hours = max(
                0.0,
                (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
                / 3600.0,
            )
        except ValueError:
            return None
    if hours is None:
        return None
    if hours < 1:
        mins = max(1, int(round(hours * 60)))
        return f"updated {mins}m ago"
    if hours < 48:
        return f"updated {int(hours)}h ago"
    return f"updated {int(hours / 24)}d ago"


def build_baseline_context(
    *,
    order_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Executive scale strip from configured providers / persisted orders.

    Omits inventory $ value when unit costs are unavailable (demo CSV default 0).
    Omits open-order $ when no priced open orders exist.
    """
    stores = product_service.list_stores()
    store_count = len(stores)
    try:
        from repositories import csv_repository

        products, inventory, _sales = csv_repository.get_frames()
        sku_count = int(products["sku"].nunique()) if not products.empty else 0
        position_count = int(len(inventory)) if inventory is not None else 0
    except Exception:  # noqa: BLE001
        pairs = batch_run_service.list_eligible_store_sku_pairs()
        sku_count = len({sku for _, sku in pairs})
        position_count = len(pairs)

    # Inventory $ only when every priced position has a positive unit cost.
    inventory_value = None
    inventory_value_display = None
    try:
        from repositories import csv_repository

        _products, inventory, _ = csv_repository.get_frames()
        total = 0.0
        priced = 0
        unpriced = 0
        for _, row in inventory.iterrows():
            try:
                product = product_service.get_product_details(str(row["sku"]))
                unit = float(product.unit_cost or 0)
            except Exception:  # noqa: BLE001
                unpriced += 1
                continue
            if unit <= 0:
                unpriced += 1
                continue
            total += unit * float(row.get("on_hand") or 0)
            priced += 1
        if priced > 0 and unpriced == 0:
            inventory_value = total
            inventory_value_display = f"${total:,.0f}"
    except Exception:  # noqa: BLE001
        pass

    summary = order_summary or {}
    open_value = float(summary.get("ready_value") or 0)
    if open_value <= 0:
        # Fall back to queued/ready count amounts only when workbench reported value.
        open_value = float(summary.get("total_value") or 0) if int(
            summary.get("ready_to_send") or summary.get("queued_for_erp") or 0
        ) > 0 else 0.0
    open_orders_display = f"${open_value:,.0f}" if open_value > 0 else None

    items: list[dict[str, Any]] = [
        {
            "key": "stores",
            "label": "Stores",
            "value": store_count,
            "display": f"{store_count:,}",
            "source": "product_provider.list_stores",
        },
        {
            "key": "skus",
            "label": "SKUs",
            "value": sku_count,
            "display": f"{sku_count:,}",
            "source": "product_master",
        },
    ]
    if inventory_value_display:
        items.append(
            {
                "key": "inventory_value",
                "label": "Inventory",
                "value": inventory_value,
                "display": inventory_value_display,
                "source": "on_hand * unit_cost",
            }
        )
    else:
        items.append(
            {
                "key": "inventory_positions",
                "label": "Inventory positions",
                "value": position_count,
                "display": f"{position_count:,}",
                "source": "inventory_feed_rows",
            }
        )
    if open_orders_display:
        items.append(
            {
                "key": "open_orders",
                "label": "Open orders",
                "value": open_value,
                "display": open_orders_display,
                "source": "purchase_order_workbench.ready_value",
            }
        )

    return {
        "store_count": store_count,
        "sku_count": sku_count,
        "inventory_positions": position_count,
        "inventory_value": inventory_value,
        "inventory_value_display": inventory_value_display,
        "open_orders_value": open_value if open_value > 0 else None,
        "open_orders_value_display": open_orders_display,
        "items": items,
    }


def _build_agent_brief(payload: dict[str, Any]) -> str:
    if not payload.get("has_run"):
        if payload.get("can_run_now"):
            return (
                "The replenishment agent has not analyzed today's inventory yet. "
                "Run it now to evaluate demand, available stock and policy rules, "
                "or wait for the scheduled analysis."
            )
        return (
            "The replenishment agent has not analyzed today's inventory yet. "
            "Automatic analysis is scheduled."
        )

    m = payload["metrics"]
    analyzed = m["items_analyzed"]
    replenish = m["recommended_for_replenishment"]
    auto = m["handled_automatically"]
    needs = m["needs_review"]
    blocked = m["blocked"]
    approved_value = m["approved_order_value_display"]
    awaiting = m["order_value_awaiting_decision_display"]

    return (
        f"Today's replenishment analysis reviewed {analyzed:,} store–SKU positions. "
        f"{replenish:,} were recommended for replenishment. "
        f"{auto:,} were handled automatically. "
        f"{needs:,} require your attention. "
        f"{blocked:,} were blocked by policy. "
        f"Approved order value is {approved_value}. "
        f"Order value awaiting your decision is {awaiting}."
    )


def _agent_status(
    *,
    has_run: bool,
    run_status: str | None,
    needs_review: int,
    scheduler_status: str | None,
    erp_ok: bool,
    active_run: bool,
    zero_key: str | None,
) -> dict[str, str]:
    if active_run or (run_status or "").lower() == "running" or zero_key == RUNNING:
        return {"key": "running", "label": "Analysis in progress", "kind": "progress"}
    if zero_key == DATA_NOT_READY:
        return {
            "key": "not_ready",
            "label": "Analysis is paused because required data is stale",
            "kind": "critical",
        }
    if zero_key == FAILED:
        return {"key": "failed", "label": "Last analysis failed", "kind": "critical"}
    if zero_key == MISSED_SCHEDULE:
        return {
            "key": "missed",
            "label": "Scheduled analysis did not start as expected",
            "kind": "attention",
        }
    if zero_key == FIRST_RUN_READY:
        return {"key": "ready", "label": "Ready for first analysis", "kind": "success"}
    if zero_key == WAITING_FOR_SCHEDULE:
        return {
            "key": "ready",
            "label": "Ready for scheduled analysis",
            "kind": "success",
        }
    if not has_run:
        return {"key": "ready", "label": "Ready for scheduled analysis", "kind": "success"}
    if (
        needs_review > 0
        or (scheduler_status or "").lower() in {"stale", "failed"}
        or not erp_ok
    ):
        return {"key": "attention", "label": "Attention needed", "kind": "attention"}
    return {
        "key": "healthy",
        "label": "Today's analysis is complete",
        "kind": "success",
    }


def _source_issue_line(source: dict[str, Any]) -> str:
    label = source.get("label") or "Data source"
    status = source.get("status") or "Unavailable"
    if status == "Unavailable":
        return f"{label} feed unavailable"
    if status == "Stale":
        return f"{label} data stale"
    return f"{label}: {status}"


def _source_is_ready(source: dict[str, Any]) -> bool:
    return source.get("status") in {"Ready", "Connected"}


def build_zero_state(
    *,
    has_run: bool,
    active_run: dict[str, Any] | None,
    latest_terminal: dict[str, Any] | None,
    schedule_enabled: bool,
    scheduler_health: dict[str, Any],
    data_sources: list[dict[str, Any]],
    next_analysis_display: str,
    can_run: bool,
    can_start_new_run: bool,
    blocking_feeds: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """
    Explicit first-run / pre-operational presentation state.

    Does not change scheduler semantics — only how health is shown to customers.
    Scheduler 'stale' with no prior successful run is treated as first-run, not a miss.
    """
    ready_n = sum(1 for d in data_sources if _source_is_ready(d))
    total_n = len(data_sources) or 1
    sources_summary = f"{ready_n}/{total_n} data sources ready"

    unavailable = [d for d in data_sources if d.get("status") == "Unavailable"]
    stale = [d for d in data_sources if d.get("status") == "Stale"]
    blocked = list(blocking_feeds or [])
    data_blocks = bool(unavailable or blocked)

    active = active_run or {}
    last = latest_terminal or {}
    last_status = str(last.get("status") or "").lower()
    last_failed = last_status in {"failed", "completed_with_errors"}
    sched_status = str(scheduler_health.get("status") or "").lower()
    last_success = scheduler_health.get("last_successful_run")
    genuine_miss = (
        schedule_enabled
        and sched_status == "stale"
        and last_success is not None
        and not active
    )

    key: str | None = None
    title = ""
    body = ""
    warning: str | None = None
    show_warning = False
    show_run_cta = False
    show_refresh = False
    footer: str | None = None
    # Exact next-run stamp lives in the global header — body uses qualitative copy.
    schedule_note = "Automatic analysis is scheduled." if schedule_enabled else (
        "Scheduled analysis is disabled."
    )
    permission_note = (
        "Manual analysis is restricted to administrators. Automatic analysis is scheduled."
        if schedule_enabled
        else "Manual analysis is restricted to administrators."
    )

    if data_blocks and not active and not has_run:
        key = DATA_NOT_READY
        stale_only = bool(stale) and not unavailable and not blocked
        title = (
            "Analysis is paused because required data is stale"
            if stale_only or (stale and not unavailable)
            else "Analysis cannot start yet"
        )
        issues = []
        for d in unavailable:
            issues.append(_source_issue_line(d))
        for d in stale[:2]:
            if d not in unavailable:
                issues.append(_source_issue_line(d))
        for b in blocked[:3]:
            issues.append(str(b.get("message") or b.get("label") or "Required data blocked"))
        body = (
            "One or more required data sources are not ready. "
            + (" ".join(issues[:3]) if issues else "Check System Health for details.")
        )
        warning = body
        show_warning = True
        show_run_cta = False
        show_refresh = False
    elif active:
        key = RUNNING
        title = "Analysis in progress"
        scored = active.get("scored_items")
        total = active.get("total_items")
        started = active.get("started_at") or active.get("created_at")
        started_disp = "—"
        if isinstance(started, str) and started:
            started_disp = started.replace("T", " ")[:16]
        if scored is not None and total is not None:
            body = (
                "Analyzing replenishment needs… "
                f"Progress: {scored}/{total} positions. Started: {started_disp}."
            )
        else:
            body = "Analysis is running. Results will appear here when complete."
        show_run_cta = False
        show_refresh = True
        footer = None
    elif last_failed and not has_run:
        key = FAILED
        title = "Last analysis failed"
        body = (
            "The previous replenishment analysis did not complete successfully. "
            "Retry when data sources are ready."
        )
        warning = body
        show_warning = True
        show_run_cta = can_run and can_start_new_run
        show_refresh = can_run
        footer = schedule_note if schedule_enabled else None
    elif genuine_miss:
        key = MISSED_SCHEDULE
        title = "Scheduled analysis did not start as expected"
        body = (
            "A replenishment analysis was expected in the schedule window "
            "but did not complete on time."
        )
        warning = body
        show_warning = True
        show_run_cta = can_run and can_start_new_run
        show_refresh = can_run
        # Contextual exception may include the exact stamp once.
        footer = (
            f"Next scheduled window: {next_analysis_display}."
            if next_analysis_display and next_analysis_display != "—"
            else schedule_note
        )
    elif not has_run:
        if can_run:
            key = FIRST_RUN_READY
            title = "Ready for first analysis"
            body = (
                "The replenishment agent has not analyzed today's inventory yet. "
                "Run it now to evaluate demand, available stock and policy rules, "
                "or wait for the scheduled analysis."
            )
            show_run_cta = can_start_new_run
            show_refresh = True  # secondary only; Run Analysis Now remains primary
            footer = None  # schedule_note is shown once in the meta strip
        else:
            key = WAITING_FOR_SCHEDULE
            title = "Ready for scheduled analysis"
            # permission_note already includes schedule guidance — show once as body.
            body = permission_note
            show_run_cta = False
            show_refresh = False
            footer = None
    else:
        return None

    return {
        "key": key,
        "title": title,
        "body": body,
        "warning": warning,
        "show_warning": show_warning,
        "show_run_cta": show_run_cta,
        "show_refresh": show_refresh,
        "footer": footer,
        "sources_summary": sources_summary,
        "sources_ready": ready_n,
        "sources_total": total_n,
        # Kept for exception paths / tests; Overview canvas must not echo it routinely.
        "next_analysis_display": next_analysis_display,
        "schedule_note": schedule_note,
        "permission_note": permission_note if not can_run else None,
        "agent_status_label": (
            "Analysis in progress"
            if key == RUNNING
            else "Ready for first analysis"
            if key == FIRST_RUN_READY
            else "Ready for scheduled analysis"
            if key == WAITING_FOR_SCHEDULE
            else "Analysis is paused because required data is stale"
            if key == DATA_NOT_READY
            else "Last analysis failed"
            if key == FAILED
            else "Scheduled analysis did not start as expected"
            if key == MISSED_SCHEDULE
            else "Attention needed"
        ),
        "compact_layout": True,
        "is_zero_state": key in _ZERO_KEYS,
    }


def get_replenishment_overview(
    *,
    actor_role: str | None = None,
    attention_limit: int = 8,
) -> dict[str, Any]:
    """
    Deterministic overview payload for the landing page.

    All counts and labels come from persisted queue / orders / scheduler / health.
    """
    role = actor_role or "viewer"
    can_run = auth_service.can_trigger_batch_run(role)
    can_decide = auth_service.can_submit_human_review(role)

    queue = queue_service.get_todays_queue(filter_key="all")
    approved = queue_service.get_approved_today(
        run_id=(queue.get("run") or {}).get("run_id")
    )
    try:
        orders = purchase_order_service.get_orders_workbench()
    except Exception:  # noqa: BLE001
        orders = {
            "summary": {"queued_for_erp": 0, "total": 0, "failed": 0},
            "adapter": {"ok": True},
        }

    trigger = scheduler_service.get_run_trigger_status()
    sched_health = trigger.get("scheduler_health") or scheduler_service.get_scheduler_health()
    try:
        ops = ops_health_service.get_operational_health()
    except Exception:  # noqa: BLE001
        ops = {"data_freshness": {}, "overall_status": "unknown", "demo": {}}

    run = queue.get("run")
    summary = queue.get("summary") or {}
    has_run = run is not None
    active = trigger.get("active_run")
    active_run = bool(active)

    needs_review = int(summary.get("needs_review") or 0)
    blocked = int(summary.get("blocked") or 0)
    auto_released = int(summary.get("auto_released") or 0)
    no_order = int(summary.get("no_order") or 0)
    items_analyzed = int((run or {}).get("scored_items") or 0)
    total_items = int((run or {}).get("total_items") or 0)
    recommended = needs_review + blocked + auto_released

    order_summary = orders.get("summary") or {}
    orders_prepared = int(
        order_summary.get("queued_for_erp")
        or order_summary.get("pending_erp")
        or 0
    )
    orders_failed = int(order_summary.get("failed") or 0)
    adapter = orders.get("adapter") or {}
    erp_ok = bool(adapter.get("ok", True))

    freshness = ops.get("data_freshness") or {}
    # Prefer structured feed freshness from ops_health when present.
    if not freshness.get("inventory") and not freshness.get("sales"):
        try:
            freshness = ops_health_service.get_feed_freshness()
        except Exception:  # noqa: BLE001
            freshness = freshness or {}
    try:
        from integrations.factory import get_provider_summary

        providers = (get_provider_summary().get("providers") or {})
    except Exception:  # noqa: BLE001
        providers = {}

    data_sources = _build_data_sources(
        freshness=freshness,
        providers=providers,
        erp_ok=erp_ok,
    )
    baseline = build_baseline_context(order_summary=order_summary)

    attention_rows: list[dict[str, Any]] = []
    for row in queue.get("rows") or []:
        if row.get("disposition") != "human_review" or not row.get("open_for_decision"):
            continue
        attention_rows.append(
            {
                "recommendation_id": row["recommendation_id"],
                "priority": _priority_label(row),
                "store": row.get("store_name")
                or product_service.store_display_name(row.get("store_id")),
                "product": row.get("item") or row.get("sku") or "—",
                "agent_recommendation": row.get("agent_quantity"),
                "why": row.get("exception") or "Needs review",
                "risk": _risk_label(row.get("risk_level")),
                "risk_level": row.get("risk_level"),
                "order_value_display": row.get("order_value_display") or "—",
            }
        )
        if len(attention_rows) >= attention_limit:
            break

    last_analysis = "—"
    if run:
        last_analysis = run.get("label") or run.get("run_id") or "—"
    elif trigger.get("last_run_display"):
        last_analysis = str(trigger.get("last_run_display"))

    next_analysis = (
        trigger.get("next_run_display")
        or sched_health.get("next_scheduled_run_display")
        or "—"
    )

    ready_n = sum(1 for d in data_sources if _source_is_ready(d))
    overall_fresh = "Ready"
    if any(d["status"] == "Unavailable" for d in data_sources):
        overall_fresh = "Unavailable"
    elif any(d["status"] == "Stale" for d in data_sources):
        overall_fresh = "Stale"

    metrics = {
        "items_analyzed": items_analyzed,
        "total_items": total_items,
        "needs_review": needs_review,
        "handled_automatically": auto_released,
        "blocked": blocked,
        "no_order": no_order,
        "recommended_for_replenishment": recommended,
        "order_value_awaiting_decision": float(
            summary.get("order_value_awaiting_decision") or 0
        ),
        "order_value_awaiting_decision_display": summary.get(
            "order_value_awaiting_decision_display"
        )
        or "$0.00",
        "approved_order_value_display": (approved.get("summary") or {}).get(
            "order_value_display"
        )
        or "$0.00",
        "orders_prepared": orders_prepared,
        "orders_failed": orders_failed,
        "approved_total": int((approved.get("summary") or {}).get("total") or 0),
        "human_approved": int((approved.get("summary") or {}).get("human_approved") or 0),
    }

    schedule_enabled = bool((trigger.get("schedule") or {}).get("enabled", True))
    can_start = bool(trigger.get("can_start_new_run", True))

    try:
        blocking_feeds = ops_health_service.required_sources_blocking_reason()
    except Exception:  # noqa: BLE001
        blocking_feeds = []

    latest_terminal = trigger.get("latest_run") or trigger.get("last_run")
    zero_state = build_zero_state(
        has_run=has_run,
        active_run=active if isinstance(active, dict) else None,
        latest_terminal=latest_terminal if isinstance(latest_terminal, dict) else None,
        schedule_enabled=schedule_enabled,
        scheduler_health=sched_health,
        data_sources=data_sources,
        next_analysis_display=next_analysis,
        can_run=can_run,
        can_start_new_run=can_start,
        blocking_feeds=blocking_feeds,
    )
    zero_key = (zero_state or {}).get("key")

    agent_status = _agent_status(
        has_run=has_run,
        run_status=(run or {}).get("status"),
        needs_review=needs_review,
        scheduler_status=sched_health.get("status"),
        erp_ok=erp_ok,
        active_run=active_run,
        zero_key=zero_key,
    )

    next_steps: list[dict[str, str]] = []
    if orders_prepared > 0:
        next_steps.append(
            {
                "label": f"{orders_prepared} order(s) awaiting transmission",
                "detail": (
                    "Approved items are prepared for the purchasing system. "
                    "Queue does not mean already sent."
                ),
            }
        )
    if schedule_enabled:
        # Exact next-run timestamp is owned by the global header — qualitative copy here.
        detail = "Scheduled analysis is enabled."
        if zero_key == MISSED_SCHEDULE:
            detail = (
                sched_health.get("message")
                or "Scheduled analysis did not start as expected."
            )
            next_steps.append(
                {
                    "label": f"Next scheduled window: {next_analysis}",
                    "detail": detail,
                }
            )
        elif has_run and (sched_health.get("status") or "").lower() == "healthy":
            next_steps.append(
                {
                    "label": "Automatic analysis is scheduled.",
                    "detail": detail,
                }
            )
        elif zero_key in {FIRST_RUN_READY, WAITING_FOR_SCHEDULE}:
            next_steps.append(
                {
                    "label": "Automatic analysis is scheduled.",
                    "detail": (
                        "Run now if authorized, or wait for the scheduled analysis."
                        if can_run
                        else "Manual analysis is restricted to administrators."
                    ),
                }
            )
        else:
            next_steps.append(
                {
                    "label": "Automatic analysis is scheduled.",
                    "detail": detail,
                }
            )
    else:
        next_steps.append(
            {
                "label": "Scheduled analysis is disabled",
                "detail": "An administrator can run analysis manually.",
            }
        )
    if orders_failed > 0:
        next_steps.append(
            {
                "label": f"{orders_failed} order(s) need send retry",
                "detail": "Review Purchase Orders for transmission issues.",
            }
        )

    # Rich operational sections only after a meaningful completed run with no zero-state card.
    show_operational = bool(has_run and zero_state is None)

    payload: dict[str, Any] = {
        "has_run": has_run,
        "run": run,
        "agent_status": agent_status,
        "last_analysis_display": last_analysis,
        "next_analysis_display": next_analysis,
        "data_freshness_label": overall_fresh,
        "data_freshness_kind": {
            "Ready": "success",
            "Stale": "attention",
            "Unavailable": "critical",
        }.get(overall_fresh, "neutral"),
        "data_sources_ready_count": ready_n,
        "data_sources_total": len(data_sources),
        "data_sources_summary": f"{ready_n}/{len(data_sources)} data sources ready",
        "metrics": metrics,
        "attention": attention_rows,
        "attention_total": needs_review,
        "handled": {
            "auto_released": auto_released,
            "no_order": no_order,
            "blocked": blocked,
            "orders_prepared": orders_prepared,
            "approved_total": metrics["approved_total"],
        },
        "next_steps": next_steps,
        "data_sources": data_sources,
        "baseline_context": baseline,
        "schedule_enabled": schedule_enabled,
        "can_run_now": can_run,
        "can_decide": can_decide,
        "can_start_new_run": can_start,
        "erp_ok": erp_ok,
        "scheduler_status": sched_health.get("status"),
        "scheduler_message": sched_health.get("message"),
        "role": role,
        "zero_state": zero_state,
        "show_operational_sections": show_operational,
        "active_run": active if isinstance(active, dict) else None,
    }
    payload["agent_brief"] = _build_agent_brief(payload)
    return payload

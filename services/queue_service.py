"""Today's Queue + Approved Today read models — persisted batch recommendations only.

No replenishment formula or policy calculation changes live here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from database.connection import get_session, init_db
from repositories import (
    approval_repository,
    order_intent_repository,
    purchase_order_repository,
    run_repository,
)
from services import product_service

QueueFilter = Literal[
    "all",
    "needs_review",
    "blocked",
    "auto_released",
    "no_order",
]

RiskFilter = Literal[
    "all",
    "stockout",
    "overstock",
    "low_confidence",
    "stale_blocked",
]

_DISPOSITION_FILTER = {
    "needs_review": "human_review",
    "blocked": "blocked",
    "auto_released": "auto_release",
    "no_order": "no_order",
}

_STATUS_LABELS = {
    "human_review": "Needs review",
    "blocked": "Blocked",
    "auto_release": "Auto-released",
    "no_order": "No order",
}

_RUN_STATUS_LABELS = {
    "completed": "Completed",
    "completed_with_errors": "Completed with errors",
    "failed": "Failed",
    "running": "Running",
    "pending": "Pending",
}

_EMPTY_MESSAGES = {
    "all": "No replenishment decisions are available for this run.",
    "needs_review": "No decisions require your review for this run.",
    "blocked": "No recommendations were blocked in this run.",
    "auto_released": "No recommendations were released automatically in this run.",
    "no_order": "No items were classified as no-order in this run.",
    "filtered": "No decisions match the selected filters.",
    "no_run": (
        "No replenishment run has completed yet. "
        "Queue items appear after the next scheduled or manual run."
    ),
}

_TERMINAL_WORKFLOW = frozenset(
    {"approved", "rejected", "approval_rejected", "declined", "ordered"}
)

_ORDER_STATUS_LABELS = {
    "pending_erp": "Ready to Send",
    "draft": "Ready to Send",
    "queued": "Ready to Send",
    "queued_for_erp": "Ready to Send",
    "transmitting": "Sending",
    "transmitted": "Completed",
    "acknowledged": "Accepted by Purchasing System",
    "erp_acknowledged": "Accepted by Purchasing System",
    "completed": "Completed",
    "in_transit": "Completed",
    "received": "Completed",
    "failed": "Send Failed",
    "transmission_failed": "Send Failed",
    "retry_pending": "Retry Scheduled",
    "erp_rejected": "Rejected by Purchasing System",
    "cancelled": "Cancelled",
    "sent": "Completed",
}


def format_order_status_label(status: str | None) -> str:
    """Business-readable order lifecycle label from persisted status."""
    from services.order_lifecycle_states import format_lifecycle_label

    return format_lifecycle_label(status)


def empty_state_message(
    *,
    filter_key: str = "all",
    has_run: bool = True,
    has_extra_filters: bool = False,
) -> str:
    if not has_run:
        return _EMPTY_MESSAGES["no_run"]
    if has_extra_filters:
        return _EMPTY_MESSAGES["filtered"]
    return _EMPTY_MESSAGES.get(filter_key, _EMPTY_MESSAGES["all"])


def _money(value: Decimal | float | int | None) -> str:
    if value is None:
        return "—"
    return f"${Decimal(str(value)):,.2f}"


_WHY_BY_RULE: dict[str, str] = {
    "inventory_freshness": "Inventory data is stale",
    "missing_critical_data": "Missing critical inventory data",
    "minimum_history": "Insufficient sales history",
    "minimum_confidence": "Confidence is below the review threshold",
    "stockout_review": "Projected demand exceeds available stock",
    "maximum_days_of_supply": "Days of supply exceeds the overstock threshold",
    "promotion_overlap": "Promotion overlap requires review",
    "auto_release_max_value": "Order value exceeds approval threshold",
    "formal_approval_value": "Order value requires formal approval",
    "zero_quantity": "No replenishment quantity is required",
    "supplier_constraint": "Supplier availability could not be verified",
}

_BLOCKED_FALLBACK_REASON = "Specific reason unavailable"
_BLOCKED_FALLBACK_GUARDRAIL = "Not recorded"
_BLOCKED_FALLBACK_ACTION = (
    "Review the underlying data and policy evaluation before retrying."
)

_GENERIC_BLOCKED_LABELS = frozenset(
    {
        "blocked",
        "stale inventory",
        "missing data",
        "insufficient history",
        "recommendation withheld",
        "cannot proceed under current policy",
    }
)

_GUARDRAIL_DISPLAY_BY_RULE: dict[str, str] = {
    "inventory_freshness": "Inventory Freshness",
    "missing_critical_data": "Missing Critical Data",
    "minimum_history": "Minimum History",
    "minimum_confidence": "Minimum Confidence",
    "supplier_constraint": "Supplier Availability Guardrail",
    "inventory_data_source": "Data Validation",
    "sales_data_source": "Data Validation",
    "products_data_source": "Data Validation",
    "zero_quantity": "Zero Quantity",
    "stockout_review": "Stockout Review",
    "maximum_days_of_supply": "Maximum Days of Supply",
    "promotion_overlap": "Promotion Overlap",
    "auto_release_max_value": "Auto-release Ceiling",
    "formal_approval_value": "Formal Approval Threshold",
}

_UNBLOCK_BY_RULE: dict[str, str] = {
    "inventory_freshness": "Refresh current inventory data, then retry scoring.",
    "missing_critical_data": (
        "Complete the missing required data fields, then retry scoring."
    ),
    "minimum_history": (
        "Wait for or load the required sales history, then retry scoring."
    ),
    "supplier_constraint": (
        "Confirm or assign an active supplier for this SKU, then retry scoring."
    ),
    "inventory_data_source": (
        "Restore inventory feed health, then retry scoring."
    ),
    "sales_data_source": "Restore sales feed health, then retry scoring.",
    "products_data_source": "Restore product feed health, then retry scoring.",
    "zero_quantity": "Resolve the policy exception before retrying the recommendation.",
}


def _guardrail_display_names() -> dict[str, str]:
    names = dict(_GUARDRAIL_DISPLAY_BY_RULE)
    try:
        from services.policy_catalog import POLICY_RULE_CATALOG

        for rule in POLICY_RULE_CATALOG:
            names.setdefault(str(rule["internal_key"]), str(rule["business_name"]))
    except Exception:  # noqa: BLE001
        pass
    return names


_GUARDRAIL_DISPLAY_NAMES = _guardrail_display_names()


def _primary_blocking_rule(
    evaluation: dict[str, Any],
    failed_rules: list[str],
) -> dict[str, Any] | None:
    rules = list(evaluation.get("evaluated_rules") or [])
    by_name = {
        str(rule.get("rule_name")): rule for rule in rules if rule.get("rule_name")
    }
    for name in failed_rules:
        rule = by_name.get(name)
        if rule and rule.get("result") == "fail" and rule.get("action") == "blocked":
            return rule
    for rule in rules:
        if rule.get("result") == "fail" and rule.get("action") == "blocked":
            return rule
    if failed_rules and failed_rules[0] in by_name:
        return by_name[failed_rules[0]]
    return None


def _unblock_from_reason_text(reason: str) -> str | None:
    low = reason.lower()
    if "supplier" in low or "vendor" in low:
        return (
            "Confirm or assign an active supplier for this SKU, then retry scoring."
        )
    if "stale" in low and "inventory" in low:
        return "Refresh current inventory data, then retry scoring."
    if "history" in low or "sales" in low:
        return (
            "Wait for or load the required sales history, then retry scoring."
        )
    if "missing" in low and ("data" in low or "input" in low):
        return (
            "Complete the missing required data fields, then retry scoring."
        )
    if "policy" in low or "hard" in low:
        return (
            "Resolve the policy exception before retrying the recommendation."
        )
    return None


def resolve_blocked_detail(
    row: dict[str, Any],
    *,
    policy_evaluation: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """User-facing blocked detail from persisted policy / evidence fields only."""
    evaluation = dict(policy_evaluation or {})
    evidence = dict(evidence or {})
    failed_rules = list(row.get("failed_rules") or evaluation.get("failed_rules") or [])
    primary_rule = _primary_blocking_rule(evaluation, failed_rules)

    blocking_reason = _blocked_reason_text(
        row=row,
        evaluation=evaluation,
        primary_rule=primary_rule,
        failed_rules=failed_rules,
    )
    guardrail = _blocked_guardrail_text(primary_rule, failed_rules)
    unblock_action = _blocked_unblock_action_text(
        primary_rule=primary_rule,
        failed_rules=failed_rules,
        blocking_reason=blocking_reason,
    )
    supplier_state = _blocked_supplier_state(
        blocking_reason=blocking_reason,
        primary_rule=primary_rule,
        evidence=evidence,
        failed_rules=failed_rules,
    )
    return {
        "blocking_reason": blocking_reason,
        "guardrail": guardrail,
        "unblock_action": unblock_action,
        "supplier_state": supplier_state,
        # Back-compat for any caller still reading blocking_stage.
        "blocking_stage": guardrail,
    }


def _blocked_reason_text(
    *,
    row: dict[str, Any],
    evaluation: dict[str, Any],
    primary_rule: dict[str, Any] | None,
    failed_rules: list[str],
) -> str:
    persisted = str(evaluation.get("blocked_reason") or "").strip()
    if persisted and persisted.lower() not in _GENERIC_BLOCKED_LABELS:
        return persisted

    if primary_rule:
        explanation = str(primary_rule.get("explanation") or "").strip()
        if explanation:
            return explanation
        rule_name = str(primary_rule.get("rule_name") or "")
        if rule_name in _WHY_BY_RULE:
            return _WHY_BY_RULE[rule_name]

    why = str(row.get("why") or "").strip()
    if why and why.lower() not in _GENERIC_BLOCKED_LABELS:
        return why

    exc = str(row.get("exception") or "").strip()
    if exc and exc.lower() not in _GENERIC_BLOCKED_LABELS:
        return exc

    for name in failed_rules:
        if name in _WHY_BY_RULE:
            return _WHY_BY_RULE[name]

    return _BLOCKED_FALLBACK_REASON


def _blocked_guardrail_text(
    primary_rule: dict[str, Any] | None,
    failed_rules: list[str],
) -> str:
    if primary_rule:
        rule_name = str(primary_rule.get("rule_name") or "")
        if rule_name:
            return _GUARDRAIL_DISPLAY_NAMES.get(
                rule_name,
                rule_name.replace("_", " ").title(),
            )
    if failed_rules:
        labels = [
            _GUARDRAIL_DISPLAY_NAMES.get(name, name.replace("_", " ").title())
            for name in failed_rules[:3]
        ]
        return ", ".join(labels)
    return _BLOCKED_FALLBACK_GUARDRAIL


def _blocked_unblock_action_text(
    *,
    primary_rule: dict[str, Any] | None,
    failed_rules: list[str],
    blocking_reason: str,
) -> str:
    if primary_rule:
        rule_name = str(primary_rule.get("rule_name") or "")
        if rule_name in _UNBLOCK_BY_RULE:
            return _UNBLOCK_BY_RULE[rule_name]
    for name in failed_rules:
        if name in _UNBLOCK_BY_RULE:
            return _UNBLOCK_BY_RULE[name]
    inferred = _unblock_from_reason_text(blocking_reason)
    if inferred:
        return inferred
    return _BLOCKED_FALLBACK_ACTION


def _blocked_supplier_state(
    *,
    blocking_reason: str,
    primary_rule: dict[str, Any] | None,
    evidence: dict[str, Any],
    failed_rules: list[str],
) -> str | None:
    rule_name = str((primary_rule or {}).get("rule_name") or "")
    low_reason = blocking_reason.lower()
    supplier_relevant = (
        rule_name == "supplier_constraint"
        or "supplier_constraint" in failed_rules
        or "supplier" in low_reason
        or "vendor" in low_reason
    )
    if rule_name == "missing_critical_data":
        observed = (primary_rule or {}).get("observed_value") or []
        if isinstance(observed, str):
            observed = [observed]
        observed_l = {str(x).lower() for x in observed}
        if "product" in observed_l or "replenishment" in observed_l:
            supplier_relevant = True

    if not supplier_relevant:
        return None

    vendor = str(evidence.get("vendor") or "").strip()
    if rule_name == "supplier_constraint" or "supplier availability" in low_reason:
        if vendor:
            return f"Supplier availability could not be verified ({vendor})"
        return "Supplier availability could not be verified"
    if not vendor:
        return "No active supplier configured"
    return vendor


def why_needs_attention(
    *,
    disposition: str | None,
    risk_level: str | None,
    failed_rules: list[str] | None,
) -> str:
    """Deterministic Why copy from persisted policy evaluation — never invents causes."""
    rules = list(failed_rules or [])
    for rule in rules:
        if rule in _WHY_BY_RULE:
            return _WHY_BY_RULE[rule]
    if disposition == "blocked":
        return "Cannot proceed under current policy"
    if disposition == "no_order":
        return "No replenishment quantity is required"
    if disposition == "auto_release":
        return "Cleared every applicable guardrail"
    if risk_level == "stockout":
        return "Projected demand exceeds available stock"
    if risk_level == "overstock":
        return "Days of supply exceeds the overstock threshold"
    if disposition == "human_review":
        return "Policy requires a human decision"
    return "Review required"


def recommendation_language(
    *,
    disposition: str | None,
    agent_quantity: object,
    case_pack: object = None,
    workflow_status: str | None = None,
) -> str:
    """Business-facing agent recommendation phrase for the workbench."""
    if workflow_status in _TERMINAL_WORKFLOW and disposition == "human_review":
        if workflow_status == "approved":
            return "Approved"
        if workflow_status in {"rejected", "approval_rejected", "declined"}:
            return "Declined"
    if disposition == "blocked":
        return "Cannot proceed"
    if disposition == "no_order":
        return "No order needed"
    if disposition == "auto_release":
        qty = _fmt_qty_units(agent_quantity)
        if qty is None:
            return "Handled automatically"
        base = f"Order {qty} units"
        cases = _case_approx(agent_quantity, case_pack)
        return f"{base}{cases}" if cases else base
    # human_review / default
    qty = _fmt_qty_units(agent_quantity)
    if qty is None:
        return "Review required"
    try:
        if float(agent_quantity) <= 0:
            return "No order needed"
    except (TypeError, ValueError):
        pass
    base = f"Order {qty} units"
    cases = _case_approx(agent_quantity, case_pack)
    return f"{base}{cases}" if cases else base


def _fmt_qty_units(value: object) -> str | None:
    if value is None:
        return None
    try:
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return f"{as_float:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        text = str(value)
        if text.lower() in {"none", "null", ""}:
            return None
        return text


def _case_approx(quantity: object, case_pack: object) -> str:
    try:
        qty = float(quantity)
        pack = int(case_pack or 0)
    except (TypeError, ValueError):
        return ""
    if pack <= 1 or qty <= 0:
        return ""
    cases = qty / pack
    if abs(cases - round(cases)) < 1e-6:
        n = int(round(cases))
        return f" (≈ {n} case{'s' if n != 1 else ''})"
    # Show one decimal when not an even pack multiple
    text = f"{cases:.1f}".rstrip("0").rstrip(".")
    return f" (≈ {text} cases)"


def priority_label(row: dict[str, Any]) -> str:
    risk = row.get("risk_level") or ""
    if risk == "stockout" or "stockout_review" in (row.get("failed_rules") or []):
        return "High"
    if row.get("disposition") == "blocked":
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


def _exception_label(
    *,
    disposition: str | None,
    risk_level: str | None,
    failed_rules: list[str],
) -> str:
    if disposition == "blocked":
        if "inventory_freshness" in failed_rules:
            return "Stale inventory"
        if "missing_critical_data" in failed_rules:
            return "Missing data"
        if "minimum_history" in failed_rules:
            return "Insufficient history"
        return "Blocked"
    if "stockout_review" in failed_rules or risk_level == "stockout":
        return "Stockout risk"
    if "minimum_confidence" in failed_rules:
        return "Low confidence"
    if "maximum_days_of_supply" in failed_rules or risk_level == "overstock":
        return "Overstock"
    if "promotion_overlap" in failed_rules:
        return "Promotion overlap"
    if "auto_release_max_value" in failed_rules:
        return "Value above release limit"
    if disposition == "auto_release":
        return "Within policy"
    if disposition == "no_order":
        return "No order needed"
    if disposition == "human_review":
        return "Needs review"
    return (risk_level or "Review").replace("_", " ").title()


def _urgency_key(row: dict[str, Any]) -> tuple:
    risk = row.get("risk_level") or ""
    disposition = row.get("disposition") or ""
    confidence = row.get("confidence")
    value = float(row.get("order_value") or 0)
    if risk == "stockout":
        bucket = 0
    elif disposition == "blocked":
        bucket = 1
    elif confidence is not None and float(confidence) < 0.75:
        bucket = 2
    elif risk == "overstock":
        bucket = 3
    elif disposition == "human_review":
        bucket = 4
    else:
        bucket = 5
    return (bucket, -value, row.get("sku") or "")


def _parse_evaluation(rec) -> tuple[list[str], float | None, float | None]:
    try:
        evaluation = json.loads(rec.policy_evaluation_json or "{}")
    except json.JSONDecodeError:
        evaluation = {}
    failed_rules = list(evaluation.get("failed_rules") or [])
    confidence = evaluation.get("confidence")
    order_value = evaluation.get("order_value")
    if order_value is not None:
        try:
            order_value = float(order_value)
        except (TypeError, ValueError):
            order_value = None
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None
    return failed_rules, confidence, order_value


def _is_open_for_queue(disposition: str, workflow_status: str) -> bool:
    """Decided human outcomes leave Needs Review; auto/block/no_order stay filterable."""
    if disposition == "human_review":
        return workflow_status not in _TERMINAL_WORKFLOW
    return True


def _display_status(disposition: str, workflow_status: str) -> tuple[str, str]:
    if workflow_status == "approved":
        return "Approved", "ok"
    if workflow_status in {"rejected", "approval_rejected", "declined"}:
        return "Declined", "danger"
    if workflow_status == "pending_approval":
        return "Awaiting approval", "warn"
    return (
        _STATUS_LABELS.get(disposition, disposition.replace("_", " ").title()),
        {
            "human_review": "warn",
            "blocked": "danger",
            "auto_release": "ok",
            "no_order": "neutral",
        }.get(disposition, "neutral"),
    )


def _store_name_map() -> dict[str, str]:
    return product_service.store_name_map()


def _row_from_recommendation(rec, store_names: dict[str, str] | None = None) -> dict[str, Any]:
    failed_rules, confidence, order_value = _parse_evaluation(rec)
    disposition = rec.disposition or "human_review"
    workflow_status = rec.status or "pending_review"
    status_label, status_kind = _display_status(disposition, workflow_status)
    store_names = store_names or {}
    store_id = rec.store_id
    case_pack = getattr(rec, "case_pack", None)
    why = why_needs_attention(
        disposition=disposition,
        risk_level=rec.risk_level,
        failed_rules=failed_rules,
    )
    rec_lang = recommendation_language(
        disposition=disposition,
        agent_quantity=rec.agent_recommended_quantity,
        case_pack=case_pack,
        workflow_status=workflow_status,
    )
    row = {
        "recommendation_id": rec.recommendation_id,
        "run_id": rec.run_id,
        "item": rec.product_name or rec.sku,
        "product_name": rec.product_name,
        "sku": rec.sku,
        "store_id": store_id,
        "store_name": store_names.get(store_id) or product_service.store_display_name(store_id),
        "exception": _exception_label(
            disposition=disposition,
            risk_level=rec.risk_level,
            failed_rules=failed_rules,
        ),
        "why": why,
        "recommendation_display": rec_lang,
        "forecast_units": rec.forecast_units,
        "days_of_supply": rec.days_of_supply,
        "agent_quantity": rec.agent_recommended_quantity,
        "usable_on_hand": int(getattr(rec, "usable_on_hand", 0) or 0),
        "safety_stock": int(getattr(rec, "safety_stock", 0) or 0),
        "in_transit": int(getattr(rec, "in_transit", 0) or 0),
        "case_pack": case_pack,
        "confidence": confidence,
        "order_value": order_value,
        "order_value_display": _money(order_value),
        "disposition": disposition,
        "workflow_status": workflow_status,
        "status": status_label,
        "status_kind": status_kind,
        "risk_level": rec.risk_level,
        "risk_label": {
            "stockout": "Stockout risk",
            "overstock": "Overstock risk",
            "balanced": "Balanced",
            "manual_review": "Needs judgment",
            "insufficient_data": "Insufficient data",
        }.get(rec.risk_level or "", (rec.risk_level or "—").replace("_", " ").title()),
        "failed_rules": failed_rules,
        "open_for_decision": _is_open_for_queue(disposition, workflow_status),
    }
    row["priority"] = priority_label(row)
    return row


def _format_run_when(value: datetime | None) -> str:
    if value is None:
        return "—"
    # Prefer local-friendly display without timezone noise.
    return value.strftime("%b %d, %Y %H:%M")


def format_run_selector_label(run: dict[str, Any]) -> str:
    """Compact label: Aug 11, 2026 06:00 — Completed — 412 scored."""
    when = run.get("completed_at") or run.get("started_at")
    if isinstance(when, datetime):
        when_label = _format_run_when(when)
    elif isinstance(when, str) and when:
        try:
            parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
            when_label = _format_run_when(parsed.replace(tzinfo=None))
        except ValueError:
            when_label = when[:16].replace("T", " ")
    else:
        when_label = "—"
    status = _RUN_STATUS_LABELS.get(
        str(run.get("status") or ""),
        str(run.get("status") or "Unknown").replace("_", " ").title(),
    )
    scored = int(run.get("scored_items") or 0)
    return f"{when_label} — {status} — {scored} scored"


def _run_selector_dict(run) -> dict[str, Any]:
    meta = {
        "run_id": run.run_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "total_items": run.total_items,
        "scored_items": run.scored_items,
        "human_review_count": int(getattr(run, "review_items", 0) or 0),
        "blocked_count": int(getattr(run, "blocked_items", 0) or 0),
        "auto_released_count": int(getattr(run, "auto_released_items", 0) or 0),
        "no_order_count": int(getattr(run, "no_order_items", 0) or 0),
        "policy_version": run.policy_version,
    }
    meta["label"] = format_run_selector_label(meta)
    return meta


def list_replenishment_runs(
    *,
    limit: int = 50,
    terminal_only: bool = True,
) -> list[dict[str, Any]]:
    """Newest-first runs for the Ops Center prior-run selector (read-only)."""
    init_db()
    with get_session() as session:
        runs = run_repository.list_runs(
            session, limit=limit, terminal_only=terminal_only
        )
        return [_run_selector_dict(run) for run in runs]


def _matches_risk(row: dict[str, Any], risk_key: str | None) -> bool:
    if not risk_key or risk_key == "all":
        return True
    risk_level = (row.get("risk_level") or "").lower()
    failed = set(row.get("failed_rules") or [])
    confidence = row.get("confidence")
    if risk_key == "stockout":
        return risk_level == "stockout" or "stockout_review" in failed
    if risk_key == "overstock":
        return risk_level == "overstock" or "maximum_days_of_supply" in failed
    if risk_key == "low_confidence":
        return "minimum_confidence" in failed or (
            confidence is not None and float(confidence) < 0.75
        )
    if risk_key == "stale_blocked":
        return row.get("disposition") == "blocked" or "inventory_freshness" in failed
    return risk_level == risk_key.lower()


def _matches_search(row: dict[str, Any], search: str | None) -> bool:
    if not search or not str(search).strip():
        return True
    needle = str(search).strip().lower()
    hay = " ".join(
        [
            str(row.get("sku") or ""),
            str(row.get("item") or ""),
            str(row.get("product_name") or ""),
        ]
    ).lower()
    return needle in hay


def _available_risk_options(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    options = [
        {"key": "all", "label": "All Risks"},
        {"key": "stockout", "label": "Stockout"},
        {"key": "overstock", "label": "Overstock"},
        {"key": "low_confidence", "label": "Low confidence"},
        {"key": "stale_blocked", "label": "Stale data / blocked"},
    ]
    known = {o["key"] for o in options}
    extras: set[str] = set()
    for row in rows:
        level = (row.get("risk_level") or "").strip().lower()
        if level and level not in known and level not in {"none", "null"}:
            extras.add(level)
    for level in sorted(extras):
        options.append({"key": level, "label": level.replace("_", " ").title()})
    return options


def get_todays_queue(
    *,
    filter_key: QueueFilter = "all",
    run_id: str | None = None,
    store_id: str | None = None,
    search: str | None = None,
    risk_key: str | None = None,
) -> dict[str, Any]:
    """
    Build Today's Queue from the latest (or specified) replenishment run.

    Filters operate only on already-persisted recommendations for the selected
    run. This method never scores, never calls OpenAI, and never creates
    recommendations.
    """
    init_db()
    store_names = _store_name_map()
    with get_session() as session:
        if run_id:
            run = run_repository.get_run(session, run_id)
        else:
            run = run_repository.get_latest_run(session, terminal_only=True)
        if run is None:
            return {
                "run": None,
                "summary": {
                    "needs_review": 0,
                    "blocked": 0,
                    "auto_released": 0,
                    "no_order": 0,
                    "order_value_awaiting_decision": 0.0,
                    "order_value_awaiting_decision_display": _money(0),
                },
                "rows": [],
                "filter": filter_key,
                "total_rows": 0,
                "empty_message": empty_state_message(has_run=False),
                "filter_options": {
                    "stores": [{"store_id": "", "store_name": "All Stores"}],
                    "risks": _available_risk_options([]),
                },
                "applied_filters": {
                    "store_id": store_id or "",
                    "search": search or "",
                    "risk_key": risk_key or "all",
                },
            }

        recommendations = run_repository.list_recommendations_for_run(session, run.run_id)
        all_rows = [
            _row_from_recommendation(rec, store_names) for rec in recommendations
        ]

    needs_review = sum(
        1
        for r in all_rows
        if r["disposition"] == "human_review" and r["open_for_decision"]
    )
    blocked = sum(1 for r in all_rows if r["disposition"] == "blocked")
    auto_released = sum(1 for r in all_rows if r["disposition"] == "auto_release")
    no_order = sum(1 for r in all_rows if r["disposition"] == "no_order")
    # Human-review open for decision ONLY — blocked excluded from awaiting value.
    awaiting_value = sum(
        float(r["order_value"] or 0)
        for r in all_rows
        if r["disposition"] == "human_review" and r["open_for_decision"]
    )

    rows = list(all_rows)
    if filter_key == "needs_review":
        rows = [
            r
            for r in rows
            if r["disposition"] == "human_review" and r["open_for_decision"]
        ]
    elif filter_key != "all":
        wanted = _DISPOSITION_FILTER[filter_key]
        rows = [r for r in rows if r["disposition"] == wanted]
    else:
        rows = [
            r
            for r in rows
            if not (
                r["disposition"] == "human_review"
                and r["workflow_status"] in _TERMINAL_WORKFLOW
            )
        ]

    store_ids_in_run = sorted({r["store_id"] for r in all_rows if r.get("store_id")})
    store_options = [{"store_id": "", "store_name": "All Stores"}] + [
        {
            "store_id": sid,
            "store_name": store_names.get(sid) or product_service.store_display_name(sid),
        }
        for sid in store_ids_in_run
    ]

    has_extra_filters = bool(
        (store_id and str(store_id).strip())
        or (search and str(search).strip())
        or (risk_key and risk_key != "all")
    )
    if store_id and str(store_id).strip():
        sid = str(store_id).strip()
        rows = [r for r in rows if r.get("store_id") == sid]
    rows = [r for r in rows if _matches_search(r, search)]
    rows = [r for r in rows if _matches_risk(r, risk_key)]

    rows.sort(key=_urgency_key)

    empty_message = None
    if not rows:
        empty_message = empty_state_message(
            filter_key=filter_key,
            has_run=True,
            has_extra_filters=has_extra_filters,
        )

    return {
        "run": {
            "run_id": run.run_id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "policy_version": run.policy_version,
            "total_items": run.total_items,
            "scored_items": run.scored_items,
            "trigger_type": run.trigger_type,
            "human_review_count": int(getattr(run, "review_items", 0) or 0),
            "blocked_count": int(getattr(run, "blocked_items", 0) or 0),
            "auto_released_count": int(getattr(run, "auto_released_items", 0) or 0),
            "no_order_count": int(getattr(run, "no_order_items", 0) or 0),
            "label": format_run_selector_label(
                {
                    "started_at": run.started_at,
                    "completed_at": run.completed_at,
                    "status": run.status,
                    "scored_items": run.scored_items,
                }
            ),
        },
        "summary": {
            "needs_review": needs_review,
            "blocked": blocked,
            "auto_released": auto_released,
            "no_order": no_order,
            "order_value_awaiting_decision": awaiting_value,
            "order_value_awaiting_decision_display": _money(awaiting_value),
        },
        "rows": rows,
        "filter": filter_key,
        "total_rows": len(rows),
        "empty_message": empty_message,
        "filter_options": {
            "stores": store_options,
            "risks": _available_risk_options(all_rows),
        },
        "applied_filters": {
            "store_id": store_id or "",
            "search": search or "",
            "risk_key": risk_key or "all",
        },
    }


def _resolve_order_status(session, recommendation_id: str) -> tuple[str | None, str]:
    intent = order_intent_repository.get_by_recommendation(session, recommendation_id)
    po = purchase_order_repository.get_purchase_order_by_recommendation(
        session, recommendation_id
    )
    raw = None
    if po is not None:
        raw = getattr(po, "order_status", None) or getattr(po, "status", None)
    if raw is None and intent is not None:
        raw = getattr(intent, "status", None)
    return raw, format_order_status_label(raw)


def get_approved_today(*, run_id: str | None = None) -> dict[str, Any]:
    """
    Approved Today: auto-released items plus human-approved recommendations
    from the latest (or specified) replenishment run.
    """
    from services.order_lifecycle_service import (
        format_released_by_label,
        display_name_for_user,
    )

    init_db()
    store_names = _store_name_map()
    with get_session() as session:
        if run_id:
            run = run_repository.get_run(session, run_id)
        else:
            run = run_repository.get_latest_run(session, terminal_only=True)
        if run is None:
            from config import ERP_AUTO_TRANSMIT

            return {
                "run": None,
                "summary": {
                    "total": 0,
                    "approved_today": 0,
                    "auto_released": 0,
                    "human_approved": 0,
                    "order_value": 0,
                    "order_value_display": _money(0),
                    "next_transmission": (
                        "Next purchasing cycle (scheduled)"
                        if ERP_AUTO_TRANSMIT
                        else "Demo mode — send when ready"
                    ),
                    "story": (
                        "The agent prepares approved orders and sends them according to "
                        "the configured purchasing schedule."
                        if ERP_AUTO_TRANSMIT
                        else (
                            "The agent prepares approved orders. In this demo environment, "
                            "an authorized user sends them to the purchasing system."
                        )
                    ),
                    "auto_transmit": ERP_AUTO_TRANSMIT,
                },
                "rows": [],
            }

        recommendations = run_repository.list_recommendations_for_run(session, run.run_id)
        rows: list[dict[str, Any]] = []
        for rec in recommendations:
            failed_rules, confidence, order_value = _parse_evaluation(rec)
            disposition = rec.disposition or "human_review"
            workflow_status = rec.status or "pending_review"

            if disposition == "auto_release":
                source = "Auto-released"
                decided_by = "policy"
                released_by = format_released_by_label(
                    released_by_type="agent_policy", approved_by=None
                )
                released_by_type = "agent_policy"
                final_qty = rec.agent_recommended_quantity
                decided_at = (
                    run.completed_at.isoformat() if run.completed_at else None
                )
            elif workflow_status == "approved":
                source = "Human approved"
                approval = approval_repository.get_latest_approval_for_recommendation(
                    session, rec.recommendation_id
                )
                decided_by = (
                    approval.approved_by if approval and approval.approved_by else "—"
                )
                released_by = display_name_for_user(
                    approval.approved_by if approval else None
                )
                released_by_type = "human"
                final_qty = (
                    approval.approved_final_quantity
                    if approval and approval.approved_final_quantity is not None
                    else rec.agent_recommended_quantity
                )
                decided_at = (
                    approval.approved_at.isoformat()
                    if approval and approval.approved_at
                    else None
                )
            else:
                continue

            order_status_raw, order_status_label = _resolve_order_status(
                session, rec.recommendation_id
            )
            release_time_display = "—"
            if decided_at:
                try:
                    parsed = datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
                    release_time_display = parsed.strftime("%b %d, %Y %H:%M")
                except ValueError:
                    release_time_display = decided_at.replace("T", " ")[:16]

            from config import ERP_AUTO_TRANSMIT
            from services.order_lifecycle_states import next_step_label

            rows.append(
                {
                    "recommendation_id": rec.recommendation_id,
                    "run_id": rec.run_id,
                    "item": rec.product_name or rec.sku,
                    "product": rec.product_name or rec.sku,
                    "sku": rec.sku,
                    "store_id": rec.store_id,
                    "store_name": store_names.get(rec.store_id)
                    or product_service.store_display_name(rec.store_id),
                    "source": source,
                    "approval_source": source,
                    "final_quantity": final_qty,
                    "agent_quantity": rec.agent_recommended_quantity,
                    "order_value": order_value,
                    "order_value_display": _money(order_value),
                    "confidence": confidence,
                    "decided_by": decided_by,
                    "released_by": released_by,
                    "released_by_type": released_by_type,
                    "decided_at": decided_at,
                    "release_time": decided_at,
                    "release_time_display": release_time_display,
                    "approved_at_display": release_time_display,
                    "order_status": order_status_raw,
                    "order_status_label": order_status_label,
                    "next_step": next_step_label(
                        order_status_raw, auto_transmit=ERP_AUTO_TRANSMIT
                    ),
                    "disposition": disposition,
                    "workflow_status": workflow_status,
                    "exception": _exception_label(
                        disposition=disposition,
                        risk_level=rec.risk_level,
                        failed_rules=failed_rules,
                    ),
                }
            )

        run_meta = {
            "run_id": run.run_id,
            "status": run.status,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "policy_version": run.policy_version,
        }

    auto_n = sum(1 for r in rows if r["source"] == "Auto-released")
    human_n = sum(1 for r in rows if r["source"] == "Human approved")
    total_value = sum(float(r["order_value"] or 0) for r in rows)
    rows.sort(key=lambda r: (0 if r["source"] == "Human approved" else 1, r["sku"]))

    from config import ERP_AUTO_TRANSMIT

    today = datetime.now(timezone.utc).date()
    approved_today_n = 0
    for r in rows:
        decided = r.get("decided_at")
        if not decided:
            continue
        try:
            parsed = datetime.fromisoformat(str(decided).replace("Z", "+00:00"))
            if parsed.astimezone(timezone.utc).date() == today:
                approved_today_n += 1
        except ValueError:
            continue

    if ERP_AUTO_TRANSMIT:
        next_transmission = "Next purchasing cycle (scheduled)"
        story = (
            "The agent prepares approved orders and sends them according to "
            "the configured purchasing schedule."
        )
    else:
        next_transmission = "Demo mode — send when ready"
        story = (
            "The agent prepares approved orders. In this demo environment, "
            "an authorized user sends them to the purchasing system."
        )

    return {
        "run": run_meta,
        "summary": {
            "total": len(rows),
            "approved_today": approved_today_n,
            "auto_released": auto_n,
            "human_approved": human_n,
            "order_value": total_value,
            "order_value_display": _money(total_value),
            "next_transmission": next_transmission,
            "story": story,
            "auto_transmit": ERP_AUTO_TRANSMIT,
        },
        "rows": rows,
    }

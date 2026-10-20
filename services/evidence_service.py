"""Recommendation evidence / explainability read model.

Assembles a decision-record view from persisted recommendation, policy
evaluation, and run metadata. Does not recalculate replenishment quantities
or call the language model.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from config import AS_OF_DATE, FORECAST_HORIZON_DAYS, FORECAST_LOOKBACK_DAYS
from database.connection import get_session, init_db
from repositories import run_repository
from services import recommendation_service
from services.queue_service import recommendation_language, why_needs_attention

StageStatus = Literal["pass", "stop", "warn", "not_evaluated", "ok"]

_BLOCKING_RULES_DEMAND = frozenset({"minimum_history", "minimum_confidence"})
_BLOCKING_RULES_INVENTORY = frozenset({"inventory_freshness"})


def _money(value: Decimal | float | int | None) -> str:
    if value is None:
        return "—"
    return f"${Decimal(str(value)):,.2f}"


def _fmt(value: Any, *, digits: int | None = None) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if digits is not None:
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _rule_map(evaluation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rule in evaluation.get("evaluated_rules") or []:
        name = rule.get("rule_name")
        if name:
            out[str(name)] = rule
    return out


def _blocking_stop(
    disposition: str | None,
    evaluation: dict[str, Any],
) -> tuple[int | None, str | None]:
    """
    Return (1-based stage that stopped, rule_name) for blocked recommendations.

    Stages: 1 demand, 2 inventory, 3 constraints, 4 guardrails.
    """
    if disposition != "blocked":
        return None, None
    rules = _rule_map(evaluation)
    missing = rules.get("missing_critical_data") or {}
    if missing.get("result") == "fail":
        observed = missing.get("observed_value") or []
        if isinstance(observed, str):
            observed = [observed]
        observed_l = {str(x).lower() for x in observed}
        if "forecast" in observed_l or "sufficient_demand_signal" in observed_l:
            return 1, "missing_critical_data"
        if "inventory" in observed_l:
            return 2, "missing_critical_data"
        if "replenishment" in observed_l:
            return 3, "missing_critical_data"
        return 1, "missing_critical_data"

    freshness = rules.get("inventory_freshness") or {}
    if freshness.get("result") == "fail" and freshness.get("action") == "blocked":
        return 2, "inventory_freshness"

    history = rules.get("minimum_history") or {}
    if history.get("result") == "fail" and history.get("action") == "blocked":
        return 1, "minimum_history"

    # Fallback: first blocked-action failure
    for rule in evaluation.get("evaluated_rules") or []:
        if rule.get("result") == "fail" and rule.get("action") == "blocked":
            name = str(rule.get("rule_name") or "")
            if name in _BLOCKING_RULES_DEMAND:
                return 1, name
            if name in _BLOCKING_RULES_INVENTORY:
                return 2, name
            return 4, name
    return 2, "blocked"


def _stage_status(
    stage_num: int,
    *,
    stop_stage: int | None,
    disposition: str | None,
    soft_fail: bool = False,
) -> StageStatus:
    if stop_stage is not None:
        if stage_num < stop_stage:
            return "pass"
        if stage_num == stop_stage:
            return "stop"
        return "not_evaluated"
    if disposition == "blocked":
        return "stop" if stage_num == 4 else "pass"
    if soft_fail:
        return "warn"
    return "pass"


def _projected_stockout_day(days_of_supply: float | None, risk_level: str | None) -> str:
    if risk_level != "stockout":
        return "—"
    if days_of_supply is None:
        return "Imminent / within horizon"
    if days_of_supply <= 0:
        return "At or past stockout"
    return f"Within ~{days_of_supply:.1f} days of supply"


_RISK_LABELS = {
    "stockout": "High",
    "overstock": "Medium",
    "balanced": "Low",
    "manual_review": "Medium",
    "insufficient_data": "Medium",
}

_STATUS_LABELS = {
    "human_review": "Needs your review",
    "blocked": "Cannot proceed",
    "auto_release": "Handled automatically",
    "no_order": "No order needed",
}

_STAGE_WHY = {
    "demand_signal": "Sets expected customer need over the planning horizon.",
    "inventory_coverage": "Shows what stock is usable now and already on the way.",
    "constraints": "Converts need into an order quantity the supply chain can ship.",
    "guardrail_check": "Applies policy thresholds that allow auto-release or require review.",
}


def _fmt_qty(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return f"{as_float:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _confidence_pct(confidence: Any) -> str:
    if confidence is None:
        return "—"
    try:
        val = float(confidence)
        if val <= 1.0:
            return f"{val * 100:.0f}%"
        return f"{val:.0f}%"
    except (TypeError, ValueError):
        return _fmt(confidence, digits=2)


def _hero_sentence(
    *,
    disposition: str | None,
    qty: Any,
    forecast: Any,
    safety: Any,
    usable: Any,
    failed_rules: list[str],
    risk_level: str | None,
    rationale: str | None,
) -> str:
    """Plain-language sentence from persisted facts only — never invents causes."""
    why = why_needs_attention(
        disposition=disposition,
        risk_level=risk_level,
        failed_rules=failed_rules,
    )
    qty_s = _fmt_qty(qty)
    if disposition == "blocked":
        return f"This item cannot proceed: {why[0].lower() + why[1:] if why else 'policy blocked the recommendation.'}"
    if disposition == "no_order":
        return "The agent recommends no order because calculated replenishment need is zero under current policy."
    if disposition == "auto_release":
        return (
            f"The agent recommends {qty_s} units and released them automatically "
            "because every applicable guardrail passed."
        )
    # Prefer deterministic stock/demand framing when those facts exist.
    if "stockout_review" in failed_rules or risk_level == "stockout":
        if forecast is not None and safety is not None and usable is not None:
            return (
                f"The agent recommends {qty_s} units because forecast demand "
                f"({_fmt_qty(forecast)}) plus safety stock ({_fmt_qty(safety)}) "
                f"exceeds usable supply ({_fmt_qty(usable)})."
            )
        return (
            f"The agent recommends {qty_s} units because forecast demand plus "
            "safety stock exceeds available supply."
        )
    if "auto_release_max_value" in failed_rules or "formal_approval_value" in failed_rules:
        return (
            f"The agent recommends {qty_s} units, but policy requires human review "
            f"because {why[0].lower() + why[1:]}."
        )
    # Persisted rationale may be used only when it does not conflict with quantities.
    text = (rationale or "").strip()
    if text and "9999" not in text and len(text) < 280:
        # Use only as soft supporting sentence when short and non-contradictory.
        pass
    return f"The agent recommends {qty_s} units. {why}."


def _next_step_copy(disposition: str | None, workflow_status: str | None) -> str:
    if disposition == "blocked":
        return (
            "Resolve the blocking condition (for example stale inventory or missing data), "
            "then retry scoring or enter a manual quantity if your role allows."
        )
    if disposition == "auto_release":
        return (
            "This item was cleared automatically. Approved quantities are prepared for "
            "the next purchasing transmission window — prepared does not mean already sent."
        )
    if disposition == "no_order":
        return "No purchase order will be prepared for this store–SKU from this analysis."
    if workflow_status in {"approved", "ordered"}:
        return (
            "Approved orders are prepared for the next purchasing transmission window. "
            "Queue does not mean the purchasing system has already accepted the order."
        )
    if workflow_status in {"rejected", "declined", "approval_rejected"}:
        return "No order will be prepared from this recommendation."
    return (
        "If you approve, the recommended quantity is locked and an order is prepared "
        "for the next purchasing transmission window. "
        "If you reject, no order is prepared from this recommendation."
    )


def _stage_outcome_summary(stage: dict[str, Any], rec: dict[str, Any], evidence: dict[str, Any]) -> str:
    key = stage.get("key")
    if key == "demand_signal":
        return f"{_fmt_qty(rec.get('forecast_units'))} units expected over next {evidence.get('forecast_days') or FORECAST_HORIZON_DAYS} days"
    if key == "inventory_coverage":
        return (
            f"{_fmt_qty(rec.get('usable_on_hand'))} usable on hand · "
            f"{_fmt_qty(rec.get('in_transit'))} in transit · "
            f"{_fmt_qty(rec.get('safety_stock'))} safety stock"
        )
    if key == "constraints":
        raw = rec.get("raw_quantity")
        rounded = evidence.get("rounded_quantity")
        if rounded is None:
            rounded = rec.get("agent_recommended_quantity")
        pack = rec.get("case_pack")
        if raw is not None and rounded is not None and pack:
            return (
                f"{_fmt_qty(raw)} units raw need → {_fmt_qty(rounded)} "
                f"(case pack {_fmt_qty(pack)})"
            )
        return f"Recommended order {_fmt_qty(rounded)} units"
    if key == "guardrail_check":
        disp = rec.get("disposition")
        return _STATUS_LABELS.get(str(disp or ""), str(disp or "—").replace("_", " ").title())
    return "—"


def get_recommendation_evidence(
    recommendation_id: str,
    *,
    rec: dict[str, Any] | None = None,
    user_id: str | None = None,
    role: str | None = None,
    check_access: bool = False,
) -> dict[str, Any]:
    """
    Build the Recommendation Detail decision-record payload from persisted data.
    """
    init_db()
    if rec is None:
        rec = recommendation_service.get_recommendation(
            recommendation_id,
            user_id=user_id,
            role=role,
            check_access=check_access,
        )
    elif check_access:
        from services import isolation_service

        isolation_service.require_recommendation_access(
            rec, user_id=user_id, role=role
        )
    elif str(rec.get("recommendation_id") or "") != str(recommendation_id):
        raise ValueError(
            f"Recommendation id mismatch: expected {recommendation_id}, "
            f"got {rec.get('recommendation_id')}"
        )
    evaluation = rec.get("policy_evaluation") or {}
    evidence = dict(rec.get("evidence") or {})
    disposition = rec.get("disposition")
    stop_stage, stop_rule = _blocking_stop(disposition, evaluation)

    run_meta: dict[str, Any] | None = None
    if rec.get("run_id"):
        with get_session() as session:
            run = run_repository.get_run(session, rec["run_id"])
        if run is not None:
            run_meta = {
                "run_id": run.run_id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "trigger_type": run.trigger_type,
                "policy_version": run.policy_version,
                "status": run.status,
            }

    decision_cutoff = None
    if run_meta and run_meta.get("completed_at"):
        decision_cutoff = run_meta["completed_at"]
    elif run_meta and run_meta.get("started_at"):
        decision_cutoff = run_meta["started_at"]
    else:
        decision_cutoff = rec.get("created_at")

    confidence = evaluation.get("confidence")
    order_value = evaluation.get("order_value")
    rules = list(evaluation.get("evaluated_rules") or [])

    # Soft fails in demand/inventory for non-blocked dispositions → warn badges
    demand_soft = any(
        r.get("result") == "fail" and r.get("rule_name") in _BLOCKING_RULES_DEMAND
        for r in rules
    ) and stop_stage is None
    inv_soft = any(
        r.get("result") == "fail" and r.get("rule_name") in _BLOCKING_RULES_INVENTORY
        for r in rules
    ) and stop_stage is None
    guard_soft = any(
        r.get("result") == "fail"
        and r.get("action") in {"human_review", "no_order", "none"}
        for r in rules
    ) and stop_stage is None

    constraints_evaluated = stop_stage is None or stop_stage > 3
    # If we have raw/case pack persisted, constraints were computed before a later stop
    if stop_stage == 2 and rec.get("raw_quantity") is not None:
        # inventory stop after replenishment may still have constraint fields — treat as N/E
        constraints_evaluated = False

    stage1_status = _stage_status(
        1, stop_stage=stop_stage, disposition=disposition, soft_fail=demand_soft
    )
    stage2_status = _stage_status(
        2, stop_stage=stop_stage, disposition=disposition, soft_fail=inv_soft
    )
    stage3_status = (
        "not_evaluated"
        if not constraints_evaluated and stop_stage is not None and stop_stage <= 2
        else _stage_status(3, stop_stage=stop_stage, disposition=disposition)
    )
    stage4_status = _stage_status(
        4, stop_stage=stop_stage, disposition=disposition, soft_fail=guard_soft
    )
    if stop_stage is not None and stop_stage <= 2:
        stage4_status = "not_evaluated"

    lookback = evidence.get("forecast_lookback_days") or FORECAST_LOOKBACK_DAYS
    horizon = evidence.get("forecast_days") or FORECAST_HORIZON_DAYS
    rounded = evidence.get("rounded_quantity")
    if rounded is None:
        rounded = rec.get("agent_recommended_quantity")
    raw_qty = rec.get("raw_quantity")
    adjustment = evidence.get("constraint_adjustment")
    if adjustment is None and raw_qty is not None and rounded is not None:
        adjustment = round(float(rounded) - float(raw_qty), 4)

    header = {
        "product_name": rec.get("product_name") or rec.get("sku"),
        "sku": rec["sku"],
        "store_id": rec["store_id"],
        "vendor": evidence.get("vendor") or "Not configured",
        "run_timestamp": (run_meta or {}).get("started_at") or rec.get("created_at"),
        "decision_cutoff": decision_cutoff,
        "as_of_date": AS_OF_DATE,
        "run_id": rec.get("run_id"),
        "recommendation_id": rec["recommendation_id"],
        "workflow_status": rec.get("status"),
    }

    decision_card = {
        "recommended_order": rec.get("agent_recommended_quantity"),
        "order_value": order_value,
        "order_value_display": _money(order_value),
        "confidence": confidence,
        "confidence_display": _fmt(confidence, digits=2),
        "arrival_lead_time": evidence.get("supplier_lead_time_days"),
        "arrival_lead_time_display": (
            f"{evidence['supplier_lead_time_days']} days"
            if evidence.get("supplier_lead_time_days") is not None
            else "Not configured"
        ),
        "arrival_estimate": evidence.get("arrival_estimate") or "—",
        "disposition": disposition,
        "risk_level": rec.get("risk_level"),
        "policy_version": rec.get("policy_version") or evaluation.get("policy_version"),
    }

    stages = [
        {
            "step": 1,
            "key": "demand_signal",
            "title": "Demand Signal",
            "status": stage1_status,
            "status_label": {
                "pass": "✓",
                "ok": "✓",
                "stop": "!",
                "warn": "!",
                "not_evaluated": "Not evaluated",
            }.get(stage1_status, stage1_status),
            "fields": [
                ("Historical demand period", f"{lookback} days trailing"),
                ("7-day forecast", _fmt(rec.get("forecast_units"), digits=1)),
                ("Average daily sales", _fmt(rec.get("average_daily_sales"), digits=2)),
                ("Forecast confidence", _fmt(confidence, digits=2)),
                (
                    "Model / version",
                    f"{evidence.get('forecast_method') or 'trailing_average'}"
                    + (
                        f" · policy {decision_card['policy_version']}"
                        if decision_card.get("policy_version")
                        else ""
                    ),
                ),
                (
                    "Forecast generated",
                    _fmt(
                        evidence.get("forecast_generated_at") or rec.get("created_at")
                    ),
                ),
            ],
        },
        {
            "step": 2,
            "key": "inventory_coverage",
            "title": "Inventory / Coverage",
            "status": stage2_status,
            "status_label": {
                "pass": "✓",
                "ok": "✓",
                "stop": "!",
                "warn": "!",
                "not_evaluated": "Not evaluated",
            }.get(stage2_status, stage2_status),
            "fields": [
                ("On hand", _fmt(evidence.get("on_hand"))),
                ("Reserved", _fmt(evidence.get("reserved", 0))),
                ("Usable on hand", _fmt(rec.get("usable_on_hand"))),
                ("In transit", _fmt(rec.get("in_transit"))),
                (
                    "Open purchase orders",
                    _fmt(evidence.get("open_order_quantity", rec.get("in_transit"))),
                ),
                ("Safety stock", _fmt(rec.get("safety_stock"))),
                ("Days of supply", _fmt(rec.get("days_of_supply"), digits=1)),
                (
                    "Projected stockout",
                    _projected_stockout_day(
                        float(rec["days_of_supply"])
                        if rec.get("days_of_supply") is not None
                        else None,
                        rec.get("risk_level"),
                    ),
                ),
            ],
        },
        {
            "step": 3,
            "key": "constraints",
            "title": "Constraints",
            "status": stage3_status,
            "status_label": {
                "pass": "✓",
                "ok": "✓",
                "stop": "!",
                "warn": "!",
                "not_evaluated": "Not evaluated",
            }.get(stage3_status, stage3_status),
            "fields": [
                ("Case pack", _fmt(rec.get("case_pack"))),
                ("Raw quantity", _fmt(raw_qty, digits=2)),
                ("Rounded quantity", _fmt(rounded)),
                (
                    "Minimum order",
                    _fmt(evidence.get("minimum_order_quantity")),
                ),
                (
                    "Maximum order",
                    _fmt(evidence.get("maximum_order_quantity")),
                ),
                (
                    "Shelf capacity",
                    _fmt(evidence.get("shelf_capacity"))
                    if evidence.get("shelf_capacity") is not None
                    else "Not configured",
                ),
                (
                    "Supplier lead time",
                    decision_card["arrival_lead_time_display"],
                ),
                (
                    "Constraint adjustment",
                    _fmt(adjustment, digits=2)
                    if stage3_status != "not_evaluated"
                    else "—",
                ),
            ],
            "constraints_applied": list(rec.get("constraints_applied") or []),
        },
        {
            "step": 4,
            "key": "guardrail_check",
            "title": "Guardrail Check",
            "status": stage4_status,
            "status_label": {
                "pass": "✓",
                "ok": "✓",
                "stop": "!",
                "warn": "!",
                "not_evaluated": "Not evaluated",
            }.get(stage4_status, stage4_status),
            "rules": [
                {
                    "rule": rule.get("rule_name"),
                    "observed_value": rule.get("observed_value"),
                    "threshold": rule.get("threshold"),
                    "result": rule.get("result"),
                    "action": rule.get("action"),
                    "explanation": rule.get("explanation"),
                }
                for rule in rules
            ]
            if stage4_status != "not_evaluated"
            else [],
            "note": (
                "Guardrails were not evaluated because processing stopped earlier."
                if stage4_status == "not_evaluated"
                else None
            ),
        },
    ]

    # For inventory-stop example: blank later stage field values visually
    if stop_stage is not None and stop_stage <= 2:
        for stage in stages:
            if stage["step"] > stop_stage and stage["step"] != 4:
                stage["fields"] = [
                    (label, "Not evaluated") for label, _ in stage.get("fields") or []
                ]

    stop_banner = None
    if stop_stage is not None:
        titles = {1: "Demand Signal", 2: "Inventory / Coverage", 3: "Constraints", 4: "Guardrail Check"}
        stop_banner = {
            "message": f"Processing stopped at step {stop_stage} of 4 — {titles[stop_stage]}",
            "stop_stage": stop_stage,
            "stop_rule": stop_rule,
        }

    customer_titles = {
        "demand_signal": "Demand",
        "inventory_coverage": "Inventory",
        "constraints": "Replenishment calculation",
        "guardrail_check": "Policy & risk",
    }
    failed_rules = list(evaluation.get("failed_rules") or [])
    for stage in stages:
        stage["customer_title"] = customer_titles.get(stage["key"], stage["title"])
        stage["why_it_matters"] = _STAGE_WHY.get(stage["key"], "")
        stage["outcome_summary"] = (
            "Not evaluated"
            if stage["status"] == "not_evaluated"
            else _stage_outcome_summary(stage, rec, evidence)
        )

    action_label = recommendation_language(
        disposition=disposition,
        agent_quantity=rec.get("agent_recommended_quantity"),
        case_pack=rec.get("case_pack"),
        workflow_status=rec.get("status"),
    )
    hero = {
        "product_name": header["product_name"],
        "sku": header["sku"],
        "store_id": header["store_id"],
        "vendor": header.get("vendor"),
        "action_label": action_label,
        "action_display": action_label.upper()
        if str(action_label).lower().startswith("order ")
        else action_label,
        "risk_level": rec.get("risk_level"),
        "risk_label": _RISK_LABELS.get(
            str(rec.get("risk_level") or ""),
            str(rec.get("risk_level") or "—").replace("_", " ").title(),
        ),
        "confidence_display": _confidence_pct(confidence),
        "order_value_display": _money(order_value),
        "status_label": _STATUS_LABELS.get(
            str(disposition or ""),
            str(disposition or "—").replace("_", " ").title(),
        ),
        "disposition": disposition,
        "sentence": _hero_sentence(
            disposition=disposition,
            qty=rec.get("agent_recommended_quantity"),
            forecast=rec.get("forecast_units"),
            safety=rec.get("safety_stock"),
            usable=rec.get("usable_on_hand"),
            failed_rules=failed_rules,
            risk_level=rec.get("risk_level"),
            rationale=rec.get("rationale"),
        ),
        "recommended_quantity": rec.get("agent_recommended_quantity"),
    }

    evidence_strip = [
        {"label": "Demand forecast", "value": _fmt_qty(rec.get("forecast_units"))},
        {"label": "On hand", "value": _fmt_qty(evidence.get("on_hand"))},
        {"label": "In transit", "value": _fmt_qty(rec.get("in_transit"))},
        {"label": "Safety stock", "value": _fmt_qty(rec.get("safety_stock"))},
        {
            "label": "Days of supply",
            "value": _fmt(rec.get("days_of_supply"), digits=1),
        },
        {"label": "Case pack", "value": _fmt_qty(rec.get("case_pack"))},
        {"label": "Order value", "value": _money(order_value)},
    ]

    # Governance: failed / review-driving rules first, plain language.
    governance_rules = []
    for rule in rules:
        governance_rules.append(
            {
                "rule": str(rule.get("rule_name") or "").replace("_", " ").title(),
                "rule_key": rule.get("rule_name"),
                "observed_value": rule.get("observed_value"),
                "threshold": rule.get("threshold"),
                "result": rule.get("result"),
                "action": rule.get("action"),
                "explanation": rule.get("explanation")
                or why_needs_attention(
                    disposition=disposition,
                    risk_level=rec.get("risk_level"),
                    failed_rules=[str(rule.get("rule_name") or "")],
                ),
            }
        )
    primary_reason = None
    for rule in governance_rules:
        if rule.get("result") == "fail":
            primary_reason = rule
            break
    governance = {
        "primary_reason": primary_reason,
        "rules": governance_rules,
        "policy_version": decision_card.get("policy_version"),
        "summary": (
            primary_reason["explanation"]
            if primary_reason
            else (
                "All evaluated policy rules passed."
                if disposition == "auto_release"
                else why_needs_attention(
                    disposition=disposition,
                    risk_level=rec.get("risk_level"),
                    failed_rules=failed_rules,
                )
            )
        ),
    }

    # Intelligence: prior decisions for same store/SKU (read-only history).
    intelligence: dict[str, Any] = {
        "operational": [],
        "historical": [],
        "knowledge": [],
    }
    try:
        history = recommendation_service.get_recommendation_history(
            rec["store_id"], rec["sku"], limit=6
        )
        for item in list(history.get("recommendations") or []):
            if item.get("recommendation_id") == recommendation_id:
                continue
            intelligence["historical"].append(
                {
                    "label": "Previous similar decision",
                    "detail": (
                        f"{item.get('status') or item.get('disposition') or '—'} · qty "
                        f"{_fmt_qty(item.get('agent_recommended_quantity'))} · "
                        f"{item.get('created_at') or '—'}"
                    ),
                }
            )
            if len(intelligence["historical"]) >= 3:
                break
    except Exception:  # noqa: BLE001
        pass
    if evidence.get("vendor") or evidence.get("supplier_lead_time_days") is not None:
        intelligence["operational"].append(
            {
                "label": "Supplier / lead time",
                "detail": (
                    f"{evidence.get('vendor') or 'Vendor not configured'} · "
                    f"lead time {decision_card['arrival_lead_time_display']}"
                ),
            }
        )
    for cite in list(evidence.get("citations") or evaluation.get("citations") or [])[:5]:
        intelligence["knowledge"].append(
            {"label": "Retrieved knowledge", "detail": str(cite)}
        )

    # Alternatives only when already persisted on the recommendation / evidence.
    alternatives: list[dict[str, Any]] = []
    raw_alts = (
        evidence.get("alternatives")
        or evaluation.get("alternatives")
        or rec.get("alternatives")
        or []
    )
    if isinstance(raw_alts, list):
        for alt in raw_alts[:5]:
            if isinstance(alt, dict):
                alternatives.append(
                    {
                        "label": alt.get("label") or alt.get("action") or "Alternative",
                        "detail": alt.get("reason")
                        or alt.get("tradeoff")
                        or alt.get("explanation")
                        or "",
                        "recommended": bool(alt.get("recommended") or alt.get("winning")),
                    }
                )

    return {
        "recommendation_id": recommendation_id,
        "header": header,
        "decision_card": decision_card,
        "hero": hero,
        "evidence_strip": evidence_strip,
        "stages": stages,
        "stop_banner": stop_banner,
        "governance": governance,
        "intelligence": intelligence,
        "alternatives": alternatives,
        "next_step": _next_step_copy(disposition, rec.get("status")),
        "explanation": {
            "text": rec.get("rationale") or "",
            "source": "persisted_rationale",
            "secondary": True,
        },
        "quantities": {
            "agent_recommended_quantity": rec.get("agent_recommended_quantity"),
            "raw_quantity": raw_qty,
            "rounded_quantity": rounded,
            "forecast_units": rec.get("forecast_units"),
        },
        "run": run_meta,
        "policy_evaluation": evaluation,
        "recommendation": {
            "disposition": disposition,
            "status": rec.get("status"),
            "case_pack": rec.get("case_pack"),
            "store_id": rec.get("store_id"),
            "sku": rec.get("sku"),
        },
    }

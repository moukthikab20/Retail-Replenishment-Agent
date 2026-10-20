"""Deterministic replenishment policy / guardrail engine.

The language model never decides auto-release. All dispositions come from
explicit rule evaluation against a versioned PolicyConfig.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from config import (
    AS_OF_DATE,
    BATCH_POLICY_VERSION,
    DEFAULT_POLICY_AUTO_RELEASE_MAX_VALUE,
    DEFAULT_POLICY_MAXIMUM_DAYS_OF_SUPPLY,
    DEFAULT_POLICY_MAXIMUM_INVENTORY_AGE_HOURS,
    DEFAULT_POLICY_MINIMUM_CONFIDENCE,
    DEFAULT_POLICY_MINIMUM_HISTORY_DAYS,
    DEFAULT_POLICY_REQUIRE_FORMAL_APPROVAL_ABOVE_VALUE,
)
from database.connection import get_session, init_db
from models.forecast import ForecastResult
from models.inventory import InventoryPosition
from models.policy import (
    PolicyConfig,
    PolicyEvaluationResult,
    PolicyRuleOutcome,
)
from models.product import Product
from models.replenishment import ReplenishmentResult
from repositories import audit_repository, policy_repository
from integrations.factory import get_sales_provider

DISPOSITION_AUTO_RELEASE = "auto_release"
DISPOSITION_HUMAN_REVIEW = "human_review"
DISPOSITION_BLOCKED = "blocked"
DISPOSITION_NO_ORDER = "no_order"

_STATUS_BY_DISPOSITION = {
    DISPOSITION_AUTO_RELEASE: "auto_released",
    DISPOSITION_HUMAN_REVIEW: "human_review_required",
    DISPOSITION_BLOCKED: "blocked",
    DISPOSITION_NO_ORDER: "no_order",
}

# Lifecycle vocabulary (plus legacy aliases accepted in comparisons).
REC_STATUS_GENERATED = "generated"
REC_STATUS_HUMAN_REVIEW_REQUIRED = "human_review_required"
REC_STATUS_AUTO_RELEASED = "auto_released"
REC_STATUS_APPROVED = "approved"
REC_STATUS_DECLINED = "declined"
REC_STATUS_BLOCKED = "blocked"


def recommendation_status_for_disposition(disposition: str) -> str:
    return _STATUS_BY_DISPOSITION.get(disposition, REC_STATUS_GENERATED)


def normalize_recommendation_status(status: str | None) -> str:
    """Map legacy statuses onto the Checkpoint 6 lifecycle vocabulary."""
    raw = (status or REC_STATUS_GENERATED).strip()
    aliases = {
        "pending_review": REC_STATUS_HUMAN_REVIEW_REQUIRED,
        "human_reviewed": REC_STATUS_HUMAN_REVIEW_REQUIRED,
        "pending_approval": REC_STATUS_HUMAN_REVIEW_REQUIRED,
        "rejected": REC_STATUS_DECLINED,
        "approval_rejected": REC_STATUS_DECLINED,
        "ordered": REC_STATUS_APPROVED,
    }
    return aliases.get(raw, raw)


def default_policy_config(
    *,
    policy_version: str | None = None,
    created_by: str = "system",
) -> PolicyConfig:
    now = datetime.now(timezone.utc)
    version = policy_version or BATCH_POLICY_VERSION
    return PolicyConfig(
        policy_id=f"POL-{version}",
        policy_version=version,
        effective_from=now,
        effective_to=None,
        active=True,
        auto_release_max_value=Decimal(str(DEFAULT_POLICY_AUTO_RELEASE_MAX_VALUE)),
        minimum_confidence=Decimal(str(DEFAULT_POLICY_MINIMUM_CONFIDENCE)),
        maximum_inventory_age_hours=int(DEFAULT_POLICY_MAXIMUM_INVENTORY_AGE_HOURS),
        maximum_days_of_supply=Decimal(str(DEFAULT_POLICY_MAXIMUM_DAYS_OF_SUPPLY)),
        minimum_history_days=int(DEFAULT_POLICY_MINIMUM_HISTORY_DAYS),
        require_review_for_stockout=True,
        require_review_for_overstock=True,
        require_review_for_promotion_overlap=True,
        maximum_override_percent=Decimal("25"),
        require_formal_approval_above_value=Decimal(
            str(DEFAULT_POLICY_REQUIRE_FORMAL_APPROVAL_ABOVE_VALUE)
        ),
        created_by=created_by,
        created_at=now,
    )


def ensure_default_policy(*, created_by: str = "system") -> PolicyConfig:
    """Persist the active default policy when none exists."""
    init_db()
    with get_session() as session:
        active = policy_repository.get_active_policy(session)
        if active is not None:
            return active
        policy = default_policy_config(created_by=created_by)
        policy_repository.save_policy(session, policy)
        audit_repository.write_audit_event(
            session,
            "policy_config_seeded",
            actor=created_by,
            details={
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
            },
        )
        return policy


def get_active_policy() -> PolicyConfig:
    init_db()
    with get_session() as session:
        active = policy_repository.get_active_policy(session)
        if active is not None:
            return active
    return ensure_default_policy()


def inventory_age_hours(
    inventory: InventoryPosition,
    *,
    as_of: datetime | None = None,
) -> float:
    ref = as_of or datetime.fromisoformat(AS_OF_DATE)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    updated = inventory.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return max(0.0, (ref - updated).total_seconds() / 3600.0)


def count_history_days(store_id: str, sku: str) -> int:
    return get_sales_provider().count_history_days(store_id, sku)


def derive_confidence(
    *,
    forecast: ForecastResult | None,
    history_days: int,
    minimum_history_days: int,
) -> Decimal:
    """Deterministic confidence proxy — never invented by the LLM."""
    if forecast is None:
        return Decimal("0")
    if forecast.method == "insufficient_data_zero":
        return Decimal("0")
    if minimum_history_days <= 0:
        return Decimal("1")
    ratio = min(Decimal("1"), Decimal(history_days) / Decimal(minimum_history_days))
    # Trailing-average forecasts with full history clear the common 0.75 gate.
    return ratio.quantize(Decimal("0.01"))


def evaluate_replenishment_policy(
    *,
    product: Product | None,
    inventory: InventoryPosition | None,
    forecast: ForecastResult | None,
    replenishment: ReplenishmentResult | None,
    risk: dict[str, Any] | None,
    open_orders: dict[str, Any] | None = None,
    policy: PolicyConfig | None = None,
    confidence: Decimal | float | None = None,
    history_days: int | None = None,
    order_value: Decimal | float | None = None,
    promotion_overlap: bool = False,
    as_of: datetime | None = None,
) -> PolicyEvaluationResult:
    """
    Evaluate every release rule and return a structured PolicyEvaluationResult.

    Disposition priority: blocked > human_review > no_order > auto_release.
    """
    del open_orders  # reserved for future inbound-policy rules
    active_policy = policy or get_active_policy()
    rules: list[PolicyRuleOutcome] = []
    warnings: list[str] = []

    recommended = (
        int(replenishment.recommended_quantity) if replenishment is not None else None
    )
    risk_level = str((risk or {}).get("risk_level") or "")
    dos = (
        float(replenishment.days_of_supply)
        if replenishment is not None and replenishment.days_of_supply is not None
        else None
    )

    store_id = (
        (inventory.store_id if inventory is not None else None)
        or (forecast.store_id if forecast is not None else None)
        or (replenishment.store_id if replenishment is not None else "")
    )
    sku = (
        (inventory.sku if inventory is not None else None)
        or (product.sku if product is not None else None)
        or (forecast.sku if forecast is not None else None)
        or (replenishment.sku if replenishment is not None else "")
    )

    hist_days = (
        int(history_days)
        if history_days is not None
        else (count_history_days(store_id, sku) if store_id and sku else 0)
    )
    conf = (
        Decimal(str(confidence))
        if confidence is not None
        else derive_confidence(
            forecast=forecast,
            history_days=hist_days,
            minimum_history_days=active_policy.minimum_history_days,
        )
    )
    if order_value is not None:
        value = Decimal(str(order_value))
    elif product is not None and recommended is not None:
        value = Decimal(str(product.unit_cost)) * Decimal(recommended)
    else:
        value = None

    # --- Rule: missing critical data ---
    missing: list[str] = []
    if product is None:
        missing.append("product")
    if inventory is None:
        missing.append("inventory")
    if forecast is None:
        missing.append("forecast")
    if replenishment is None:
        missing.append("replenishment")
    if risk is None:
        missing.append("risk")
    if risk_level == "insufficient_data":
        missing.append("sufficient_demand_signal")
    missing_fail = bool(missing)
    rules.append(
        PolicyRuleOutcome(
            rule_name="missing_critical_data",
            observed_value=missing or None,
            threshold="product,inventory,forecast,replenishment,risk",
            result="fail" if missing_fail else "pass",
            action="blocked" if missing_fail else "none",
            explanation=(
                f"Missing critical inputs: {', '.join(missing)}"
                if missing_fail
                else "All critical scoring inputs are present"
            ),
        )
    )

    # --- Rule: required data-source freshness (ops health → policy block) ---
    from services import ops_health_service

    for feed_issue in ops_health_service.required_sources_blocking_reason(as_of=as_of):
        rules.append(
            PolicyRuleOutcome(
                rule_name=str(feed_issue["rule_name"]),
                observed_value=feed_issue.get("status"),
                threshold="healthy",
                result="fail",
                action="blocked",
                explanation=(
                    f"{feed_issue.get('label') or feed_issue.get('source')}: "
                    f"{feed_issue.get('message')}"
                ),
            )
        )

    # --- Rule: inventory freshness ---
    if inventory is None:
        age_hours = None
        freshness_result: str = "skip"
        freshness_fail = False
        freshness_explanation = "Inventory unavailable; freshness not evaluated"
    else:
        age_hours = round(inventory_age_hours(inventory, as_of=as_of), 2)
        freshness_fail = age_hours > float(active_policy.maximum_inventory_age_hours)
        freshness_result = "fail" if freshness_fail else "pass"
        freshness_explanation = (
            f"Inventory age {age_hours}h exceeds "
            f"{active_policy.maximum_inventory_age_hours}h"
            if freshness_fail
            else f"Inventory age {age_hours}h within freshness limit"
        )
    rules.append(
        PolicyRuleOutcome(
            rule_name="inventory_freshness",
            observed_value=age_hours,
            threshold=active_policy.maximum_inventory_age_hours,
            result=freshness_result,  # type: ignore[arg-type]
            action="blocked" if freshness_fail else "none",
            explanation=freshness_explanation,
        )
    )

    # --- Rule: minimum history ---
    history_fail = hist_days < int(active_policy.minimum_history_days)
    rules.append(
        PolicyRuleOutcome(
            rule_name="minimum_history",
            observed_value=hist_days,
            threshold=active_policy.minimum_history_days,
            result="fail" if history_fail else "pass",
            action="blocked" if history_fail else "none",
            explanation=(
                f"Only {hist_days} history day(s); need "
                f"{active_policy.minimum_history_days}"
                if history_fail
                else f"History coverage {hist_days} day(s) meets minimum"
            ),
        )
    )

    # --- Rule: confidence ---
    conf_fail = conf < active_policy.minimum_confidence
    rules.append(
        PolicyRuleOutcome(
            rule_name="minimum_confidence",
            observed_value=float(conf),
            threshold=float(active_policy.minimum_confidence),
            result="fail" if conf_fail else "pass",
            action="human_review" if conf_fail else "none",
            explanation=(
                f"Confidence {conf} below minimum {active_policy.minimum_confidence}"
                if conf_fail
                else f"Confidence {conf} meets minimum {active_policy.minimum_confidence}"
            ),
        )
    )

    # --- Rule: stockout review ---
    is_stockout = risk_level == "stockout"
    stockout_fail = bool(is_stockout and active_policy.require_review_for_stockout)
    rules.append(
        PolicyRuleOutcome(
            rule_name="stockout_review",
            observed_value=risk_level or None,
            threshold={
                "require_review_for_stockout": active_policy.require_review_for_stockout
            },
            result="fail" if stockout_fail else ("pass" if is_stockout else "skip"),
            action="human_review" if stockout_fail else "none",
            explanation=(
                "Stockout risk requires human review under active policy"
                if stockout_fail
                else (
                    "Stockout risk present but review not required by policy"
                    if is_stockout
                    else "Stockout review rule not applicable"
                )
            ),
        )
    )

    # --- Rule: overstock / max DOS ---
    over_dos = dos is not None and Decimal(str(dos)) > active_policy.maximum_days_of_supply
    if over_dos and recommended == 0:
        over_action = DISPOSITION_NO_ORDER
        over_fail = True
        over_explanation = (
            f"Days of supply {dos} above {active_policy.maximum_days_of_supply} "
            "with zero recommended quantity → no order"
        )
    elif over_dos and active_policy.require_review_for_overstock:
        over_action = DISPOSITION_HUMAN_REVIEW
        over_fail = True
        over_explanation = (
            f"Days of supply {dos} above {active_policy.maximum_days_of_supply}; "
            "overstock requires human review"
        )
    elif over_dos:
        over_action = "none"
        over_fail = False
        over_explanation = (
            f"Days of supply {dos} above maximum but overstock review disabled"
        )
        warnings.append(over_explanation)
    else:
        over_action = "none"
        over_fail = False
        over_explanation = (
            f"Days of supply {dos} within maximum {active_policy.maximum_days_of_supply}"
            if dos is not None
            else "Days of supply unavailable; overstock rule skipped"
        )
    rules.append(
        PolicyRuleOutcome(
            rule_name="maximum_days_of_supply",
            observed_value=dos,
            threshold=float(active_policy.maximum_days_of_supply),
            result=(
                "fail"
                if over_fail
                else ("pass" if dos is not None else "skip")
            ),
            action=over_action,  # type: ignore[arg-type]
            explanation=over_explanation,
        )
    )

    # --- Rule: promotion overlap ---
    promo_fail = bool(
        promotion_overlap and active_policy.require_review_for_promotion_overlap
    )
    rules.append(
        PolicyRuleOutcome(
            rule_name="promotion_overlap",
            observed_value=promotion_overlap,
            threshold={
                "require_review_for_promotion_overlap": (
                    active_policy.require_review_for_promotion_overlap
                )
            },
            result="fail" if promo_fail else ("pass" if promotion_overlap else "skip"),
            action="human_review" if promo_fail else "none",
            explanation=(
                "Promotion overlap requires human review"
                if promo_fail
                else (
                    "Promotion overlap present but review not required"
                    if promotion_overlap
                    else "No promotion overlap signal"
                )
            ),
        )
    )

    # --- Rule: zero / no-order quantity ---
    zero_qty = recommended is not None and recommended <= 0
    rules.append(
        PolicyRuleOutcome(
            rule_name="zero_quantity",
            observed_value=recommended,
            threshold=0,
            result="fail" if zero_qty else ("pass" if recommended is not None else "skip"),
            action="no_order" if zero_qty else "none",
            explanation=(
                "Recommended quantity is zero; no purchase order required"
                if zero_qty
                else f"Recommended quantity {recommended} is positive"
            ),
        )
    )

    # --- Rule: auto-release order value ceiling ---
    if value is None:
        value_fail = False
        value_result = "skip"
        value_explanation = "Order value unavailable; ceiling not evaluated"
        value_action = "none"
    else:
        value_fail = value > active_policy.auto_release_max_value
        value_result = "fail" if value_fail else "pass"
        value_action = "human_review" if value_fail else "none"
        value_explanation = (
            f"Order value {value} exceeds auto-release ceiling "
            f"{active_policy.auto_release_max_value}"
            if value_fail
            else (
                f"Order value {value} within auto-release ceiling "
                f"{active_policy.auto_release_max_value}"
            )
        )
    rules.append(
        PolicyRuleOutcome(
            rule_name="auto_release_max_value",
            observed_value=float(value) if value is not None else None,
            threshold=float(active_policy.auto_release_max_value),
            result=value_result,  # type: ignore[arg-type]
            action=value_action,  # type: ignore[arg-type]
            explanation=value_explanation,
        )
    )

    # --- Rule: formal approval threshold (warning / review signal) ---
    if value is None:
        formal_fail = False
        formal_result = "skip"
        formal_explanation = "Order value unavailable; formal-approval threshold skipped"
    else:
        formal_fail = value > active_policy.require_formal_approval_above_value
        formal_result = "fail" if formal_fail else "pass"
        formal_explanation = (
            f"Order value {value} exceeds formal approval threshold "
            f"{active_policy.require_formal_approval_above_value}"
            if formal_fail
            else (
                f"Order value {value} within formal approval threshold "
                f"{active_policy.require_formal_approval_above_value}"
            )
        )
        if formal_fail:
            warnings.append(formal_explanation)
    rules.append(
        PolicyRuleOutcome(
            rule_name="formal_approval_value",
            observed_value=float(value) if value is not None else None,
            threshold=float(active_policy.require_formal_approval_above_value),
            result=formal_result,  # type: ignore[arg-type]
            action="human_review" if formal_fail else "none",
            explanation=formal_explanation,
        )
    )

    failed_rules = [rule.rule_name for rule in rules if rule.result == "fail"]
    has_blocked = any(
        rule.result == "fail" and rule.action == DISPOSITION_BLOCKED for rule in rules
    )
    has_review = any(
        rule.result == "fail" and rule.action == DISPOSITION_HUMAN_REVIEW
        for rule in rules
    )
    has_no_order = any(
        rule.result == "fail" and rule.action == DISPOSITION_NO_ORDER for rule in rules
    )

    # Priority: blocked > zero-qty/no_order > human_review > auto_release.
    if has_blocked:
        disposition = DISPOSITION_BLOCKED
    elif recommended is not None and recommended <= 0:
        disposition = DISPOSITION_NO_ORDER
    elif has_review:
        disposition = DISPOSITION_HUMAN_REVIEW
    elif has_no_order:
        disposition = DISPOSITION_NO_ORDER
    else:
        disposition = DISPOSITION_AUTO_RELEASE

    passed = disposition == DISPOSITION_AUTO_RELEASE
    return PolicyEvaluationResult(
        disposition=disposition,  # type: ignore[arg-type]
        passed=passed,
        failed_rules=failed_rules,
        warnings=warnings,
        evaluated_rules=rules,
        policy_version=active_policy.policy_version,
        policy_id=active_policy.policy_id,
        recommendation_status=recommendation_status_for_disposition(disposition),
        order_value=value,
        confidence=conf,
    )


def save_policy_config(policy: PolicyConfig, *, actor: str = "system") -> PolicyConfig:
    """Persist a policy version. Deactivates other actives when this one is active."""
    init_db()
    with get_session() as session:
        if policy.active:
            current = policy_repository.get_active_policy(session)
            if current is not None and current.policy_id != policy.policy_id:
                deactivated = current.model_copy(
                    update={
                        "active": False,
                        "effective_to": datetime.now(timezone.utc),
                    }
                )
                policy_repository.save_policy(session, deactivated)
        saved = policy_repository.save_policy(session, policy)
        audit_repository.write_audit_event(
            session,
            "policy_config_saved",
            actor=actor,
            details={
                "policy_id": saved.policy_id,
                "policy_version": saved.policy_version,
                "active": saved.active,
            },
        )
        return saved


def next_policy_version(current_version: str) -> str:
    raw = (current_version or "").strip()
    if raw.startswith("v") and raw[1:].isdigit():
        return f"v{int(raw[1:]) + 1}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"v{stamp}"


def list_policy_versions(*, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with get_session() as session:
        rows = policy_repository.list_policies(session, limit=limit)
    return [
        {
            "policy_id": p.policy_id,
            "policy_version": p.policy_version,
            "active": p.active,
            "created_by": p.created_by,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "effective_from": p.effective_from.isoformat() if p.effective_from else None,
            "effective_to": p.effective_to.isoformat() if p.effective_to else None,
        }
        for p in rows
    ]


def get_policy_guardrails_view() -> dict[str, Any]:
    """Read model for the Policy & Guardrails page (no mutations)."""
    from services.policy_catalog import rule_rows_for_policy

    policy = get_active_policy()
    return {
        "policy": policy.model_dump(mode="json"),
        "policy_version": policy.policy_version,
        "policy_id": policy.policy_id,
        "active": policy.active,
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "effective_from": policy.effective_from.isoformat() if policy.effective_from else None,
        "rules": rule_rows_for_policy(policy),
        "versions": list_policy_versions(limit=20),
    }


def publish_policy_version(
    *,
    actor: str,
    actor_role: str,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """
    Publish a *new* policy version from an administrator edit.

    - Never mutates threshold fields on the prior version row.
    - Prior version is deactivated and closed with effective_to.
    - Recommendations keep their stored policy_version forever.
    """
    from services import auth_service

    auth_service.require_permission(
        actor_role,
        auth_service.can_edit_policy(actor_role),
        "publish a policy version",
    )
    if not changes:
        raise ValueError("No policy changes provided")

    allowed_fields = {
        "auto_release_max_value",
        "minimum_confidence",
        "maximum_inventory_age_hours",
        "maximum_days_of_supply",
        "minimum_history_days",
        "require_review_for_stockout",
        "require_review_for_overstock",
        "require_review_for_promotion_overlap",
        "maximum_override_percent",
        "require_formal_approval_above_value",
    }
    unknown = set(changes) - allowed_fields
    if unknown:
        raise ValueError(f"Unsupported policy fields: {sorted(unknown)}")

    ensure_default_policy(created_by=actor)
    init_db()
    now = datetime.now(timezone.utc)
    with get_session() as session:
        current = policy_repository.get_active_policy(session)
        if current is None:
            raise ValueError("No active policy available to supersede")

        # Snapshot prior values before deactivation (immutability for history).
        prior_snapshot = current.model_dump(mode="json")
        prior_id = current.policy_id
        prior_version = current.policy_version

        new_version = next_policy_version(prior_version)
        while policy_repository.get_policy_by_version(session, new_version) is not None:
            new_version = next_policy_version(new_version)

        updates: dict[str, Any] = {}
        for key, value in changes.items():
            if key in {
                "auto_release_max_value",
                "minimum_confidence",
                "maximum_days_of_supply",
                "maximum_override_percent",
                "require_formal_approval_above_value",
            }:
                updates[key] = Decimal(str(value))
            elif key in {"maximum_inventory_age_hours", "minimum_history_days"}:
                updates[key] = int(value)
            else:
                updates[key] = bool(value)

        # Close prior version — do not rewrite its configured thresholds.
        closed = current.model_copy(update={"active": False, "effective_to": now})
        policy_repository.save_policy(session, closed)

        created = current.model_copy(
            update={
                **updates,
                "policy_id": f"POL-{uuid4().hex[:12]}",
                "policy_version": new_version,
                "effective_from": now,
                "effective_to": None,
                "active": True,
                "created_by": actor,
                "created_at": now,
            }
        )
        saved = policy_repository.save_policy(session, created)
        audit_repository.write_audit_event(
            session,
            "policy_version_published",
            actor=actor,
            actor_role=actor_role,
            details={
                "policy_id": saved.policy_id,
                "policy_version": saved.policy_version,
                "supersedes_policy_id": prior_id,
                "supersedes_policy_version": prior_version,
                "changes": {k: str(v) for k, v in updates.items()},
                "published_at": now.isoformat(),
            },
        )

    return {
        "policy_id": saved.policy_id,
        "policy_version": saved.policy_version,
        "supersedes_policy_id": prior_id,
        "supersedes_policy_version": prior_version,
        "created_by": actor,
        "created_at": now.isoformat(),
        "changes": {k: str(v) for k, v in updates.items()},
        "prior_snapshot": prior_snapshot,
        "active": True,
    }

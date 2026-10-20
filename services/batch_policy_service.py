"""Compatibility facade for batch disposition → policy engine.

Batch scoring should call policy_service.evaluate_replenishment_policy.
This module keeps earlier imports working.
"""

from __future__ import annotations

from typing import Any

from models.inventory import InventoryPosition
from models.replenishment import ReplenishmentResult
from services import policy_service

DISPOSITION_AUTO_RELEASE = policy_service.DISPOSITION_AUTO_RELEASE
DISPOSITION_HUMAN_REVIEW = policy_service.DISPOSITION_HUMAN_REVIEW
DISPOSITION_BLOCKED = policy_service.DISPOSITION_BLOCKED
DISPOSITION_NO_ORDER = policy_service.DISPOSITION_NO_ORDER


def policy_version() -> str:
    return policy_service.get_active_policy().policy_version


def recommendation_status_for_disposition(disposition: str) -> str:
    return policy_service.recommendation_status_for_disposition(disposition)


def evaluate_disposition(
    *,
    inventory: InventoryPosition,
    replenishment: ReplenishmentResult,
    risk: dict[str, Any],
    open_orders: dict[str, Any] | None = None,
    product=None,
    forecast=None,
    confidence=None,
    history_days=None,
    order_value=None,
    promotion_overlap: bool = False,
    policy=None,
) -> dict[str, Any]:
    """Backward-compatible wrapper returning a dict shaped PolicyEvaluationResult."""
    result = policy_service.evaluate_replenishment_policy(
        product=product,
        inventory=inventory,
        forecast=forecast,
        replenishment=replenishment,
        risk=risk,
        open_orders=open_orders,
        policy=policy,
        confidence=confidence,
        history_days=history_days,
        order_value=order_value,
        promotion_overlap=promotion_overlap,
    )
    payload = result.model_dump(mode="json")
    payload["reasons"] = [
        rule["explanation"]
        for rule in payload.get("evaluated_rules") or []
        if rule.get("result") == "fail"
    ]
    return payload

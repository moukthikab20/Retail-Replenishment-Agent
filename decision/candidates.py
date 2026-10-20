"""Candidate generation — typed action alternatives."""

from __future__ import annotations

from uuid import uuid4

from decision.contracts import DecisionCandidate, DecisionContext
from decision.types import ACTION_LABELS, DecisionAction


def _cid(action: DecisionAction) -> str:
    return f"CAND-{action.value}-{uuid4().hex[:6].upper()}"


def generate_candidates(context: DecisionContext) -> list[DecisionCandidate]:
    """
    Produce the standard replenishment decision set.
    Does not execute actions — evaluation only.
    """
    inventory = context.inventory or {}
    policy = context.policy
    on_hand = _num(inventory.get("on_hand") or inventory.get("usable_on_hand"))
    forecast = _num(
        (context.recommendation or {}).get("forecast_units")
        or inventory.get("forecast_units")
    )
    recommended_qty = _num((context.recommendation or {}).get("recommended_quantity"))

    candidates: list[DecisionCandidate] = []

    def add(action: DecisionAction, description: str, *, eligible: bool = True, reason: str | None = None):
        candidates.append(
            DecisionCandidate(
                candidate_id=_cid(action),
                action=action,
                label=ACTION_LABELS[action],
                description=description,
                eligible=eligible,
                ineligibility_reason=reason,
            )
        )

    add(
        DecisionAction.CREATE_PURCHASE_ORDER,
        "Create a purchase order for the recommended replenishment quantity.",
        eligible=not policy.blocked,
        reason="Blocked by policy" if policy.blocked else None,
    )
    add(
        DecisionAction.TRANSFER_INVENTORY,
        "Transfer stock from another store or DC instead of purchasing.",
        eligible=on_hand is not None,
    )
    add(
        DecisionAction.DELAY_PURCHASE,
        "Defer purchasing until inventory risk or supplier conditions improve.",
    )
    add(
        DecisionAction.SPLIT_ORDER,
        "Split the order across shipments or suppliers to reduce risk.",
        eligible=recommended_qty is not None and recommended_qty > 0,
        reason="No positive recommended quantity" if not (recommended_qty and recommended_qty > 0) else None,
    )
    add(
        DecisionAction.ESCALATE_APPROVAL,
        "Escalate for Category Manager / formal approval before execution.",
    )
    add(
        DecisionAction.CHANGE_SUPPLIER,
        "Switch to an alternate supplier when reliability or lead time is poor.",
        eligible=bool(context.supplier_id or (context.supplier_history or {})),
        reason="No supplier context" if not (context.supplier_id or context.supplier_history) else None,
    )
    add(
        DecisionAction.WAIT_FOR_HUMAN,
        "Pause automated action and wait for a human decision.",
    )
    add(
        DecisionAction.REJECT_RECOMMENDATION,
        "Reject the current recommendation without placing an order.",
    )
    add(
        DecisionAction.NO_ACTION,
        "Take no replenishment action in this cycle.",
        eligible=forecast is None or (on_hand is not None and forecast is not None and on_hand >= forecast),
        reason="Inventory appears below forecast — no-action may be inappropriate"
        if on_hand is not None and forecast is not None and on_hand < forecast
        else None,
    )
    return candidates


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

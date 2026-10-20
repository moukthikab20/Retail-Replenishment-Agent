"""Validators — policy precedence and hard-rule enforcement."""

from __future__ import annotations

from decision.contracts import DecisionCandidate, DecisionContext, DecisionPolicyResult
from decision.types import DecisionAction


def extract_policy_result(raw: dict | None) -> DecisionPolicyResult:
    data = dict(raw or {})
    disposition = str(
        data.get("disposition")
        or data.get("policy_disposition")
        or data.get("result")
        or ""
    ).strip().lower() or None
    blocked = bool(data.get("blocked")) or disposition in {"blocked", "block", "reject"}
    requires_human = bool(data.get("requires_human") or data.get("human_review")) or disposition in {
        "human_review",
        "escalate",
        "escalation",
        "require_approval",
    }
    if disposition == "auto_release":
        requires_human = False
        blocked = False
    policy_ids = []
    for key in ("policy_id", "policy_ids", "rule_ids"):
        val = data.get(key)
        if isinstance(val, list):
            policy_ids.extend(str(x) for x in val)
        elif val:
            policy_ids.append(str(val))
    reasons = []
    if data.get("reason"):
        reasons.append(str(data["reason"]))
    if data.get("reasons") and isinstance(data["reasons"], list):
        reasons.extend(str(r) for r in data["reasons"])
    return DecisionPolicyResult(
        disposition=disposition,
        requires_human=requires_human,
        blocked=blocked,
        policy_ids=policy_ids,
        reasons=reasons,
        hard_rule_applied=blocked or requires_human,
        raw=data,
    )


def apply_policy_precedence(
    candidates: list[DecisionCandidate], context: DecisionContext
) -> list[DecisionCandidate]:
    """
    Hard business rules win: mark execute-style candidates ineligible when policy blocks
    or requires human, before strategy selection.
    """
    policy = context.policy
    for cand in candidates:
        action = str(cand.action)
        if policy.blocked and action == DecisionAction.CREATE_PURCHASE_ORDER:
            cand.eligible = False
            cand.ineligibility_reason = "Hard policy block prevents purchase order creation."
        if policy.requires_human and action == DecisionAction.CREATE_PURCHASE_ORDER:
            # Prefer escalate path — PO create remains possible only after human.
            cand.eligible = False
            cand.ineligibility_reason = (
                "Policy requires human approval before purchase order creation."
            )
        if policy.blocked and action in {
            DecisionAction.SPLIT_ORDER,
            DecisionAction.CHANGE_SUPPLIER,
            DecisionAction.TRANSFER_INVENTORY,
        }:
            cand.eligible = False
            cand.ineligibility_reason = "Hard policy block prevents fulfillment actions."
    return candidates


def should_escalate(
    *,
    winning: DecisionCandidate,
    confidence_score: float,
    max_risk: float,
    confidence_floor: float,
    risk_ceiling: float,
    policy: DecisionPolicyResult,
) -> bool:
    if policy.requires_human or policy.blocked:
        return True
    if str(winning.action) in {
        DecisionAction.WAIT_FOR_HUMAN,
        DecisionAction.ESCALATE_APPROVAL,
    }:
        return True
    if confidence_score < confidence_floor:
        return True
    if max_risk >= risk_ceiling:
        return True
    return False

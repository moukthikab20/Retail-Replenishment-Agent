"""Scoring engine — explainable per-dimension scores."""

from __future__ import annotations

from decision.contracts import (
    DecisionCandidate,
    DecisionContext,
    DecisionFactor,
    DecisionRisk,
    DecisionScore,
)
from decision.types import DecisionAction, RiskCategory, RiskLevel, ScoreDimension


def score_candidate(
    candidate: DecisionCandidate, context: DecisionContext
) -> DecisionCandidate:
    """Attach dimension scores, risks, and total_score. Higher total is better."""
    if not candidate.eligible:
        candidate.total_score = -1.0
        candidate.scores = []
        candidate.risks = [
            DecisionRisk(
                category=RiskCategory.OPERATIONAL,
                level=RiskLevel.HIGH,
                score=0.8,
                explanation=candidate.ineligibility_reason or "Candidate ineligible",
            )
        ]
        return candidate

    action = str(candidate.action)
    scores: list[DecisionScore] = []
    risks: list[DecisionRisk] = []
    factors: list[DecisionFactor] = []

    policy = context.policy
    inventory = context.inventory or {}
    recommendation = context.recommendation or {}
    supplier = context.supplier_history or {}
    erp = context.erp_state or {}

    # Policy compliance — hard preference for escalate/wait when policy requires human
    if policy.blocked and action in {
        DecisionAction.REJECT_RECOMMENDATION,
        DecisionAction.WAIT_FOR_HUMAN,
        DecisionAction.NO_ACTION,
    }:
        policy_score = 1.0
        policy_expl = "Aligns with blocked disposition."
    elif policy.requires_human and action in {
        DecisionAction.ESCALATE_APPROVAL,
        DecisionAction.WAIT_FOR_HUMAN,
    }:
        policy_score = 1.0
        policy_expl = "Aligns with human-review / escalation policy."
    elif policy.blocked and action == DecisionAction.CREATE_PURCHASE_ORDER:
        policy_score = 0.0
        policy_expl = "Violates blocked policy — cannot create PO."
    elif policy.requires_human and action == DecisionAction.CREATE_PURCHASE_ORDER:
        policy_score = 0.25
        policy_expl = "Policy requires human review before PO creation."
    elif action == DecisionAction.CREATE_PURCHASE_ORDER:
        policy_score = 0.85
        policy_expl = "No hard policy block against creating a PO."
    else:
        policy_score = 0.6
        policy_expl = "Neutral policy fit."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.POLICY_COMPLIANCE,
            score=policy_score,
            weight=1.5,
            explanation=policy_expl,
        )
    )

    # Inventory risk (higher score = better mitigation of stockout)
    on_hand = _f(inventory.get("on_hand") or inventory.get("usable_on_hand"))
    dos = _f(inventory.get("days_of_supply") or recommendation.get("days_of_supply"))
    stockout_pressure = 0.0
    if dos is not None and dos < 3:
        stockout_pressure = 0.9
    elif dos is not None and dos < 7:
        stockout_pressure = 0.55
    elif on_hand is not None and on_hand <= 0:
        stockout_pressure = 1.0
    if action == DecisionAction.CREATE_PURCHASE_ORDER:
        inv_score = 0.2 + 0.8 * stockout_pressure
        inv_expl = "PO addresses inventory pressure." if stockout_pressure else "PO optional at current DOS."
    elif action == DecisionAction.TRANSFER_INVENTORY:
        inv_score = 0.55 + 0.3 * stockout_pressure
        inv_expl = "Transfer can relieve local stockout without new PO."
    elif action in {DecisionAction.DELAY_PURCHASE, DecisionAction.NO_ACTION}:
        inv_score = max(0.05, 0.9 - stockout_pressure)
        inv_expl = "Delay/no-action worsens when stockout pressure is high."
    elif action == DecisionAction.SPLIT_ORDER:
        inv_score = 0.5 + 0.3 * stockout_pressure
        inv_expl = "Split order partially covers demand."
    else:
        inv_score = 0.45
        inv_expl = "Indirect inventory impact."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.INVENTORY_RISK,
            score=_clamp(inv_score),
            weight=1.2,
            explanation=inv_expl,
        )
    )
    risks.append(
        DecisionRisk(
            category=RiskCategory.INVENTORY,
            level=_level(stockout_pressure),
            score=stockout_pressure,
            explanation=f"Stockout pressure={stockout_pressure:.2f} (DOS={dos}).",
        )
    )

    # Supplier reliability
    reliability = _f(supplier.get("reliability") or supplier.get("on_time_rate"))
    if reliability is None:
        reliability = 0.7
        factors.append(
            DecisionFactor(
                name="supplier_reliability_defaulted",
                value=reliability,
                explanation="Supplier reliability not provided; used neutral default 0.7.",
            )
        )
    if action == DecisionAction.CHANGE_SUPPLIER:
        sup_score = 0.9 if reliability < 0.6 else 0.35
        sup_expl = "Change supplier favored when reliability is weak."
    elif action == DecisionAction.CREATE_PURCHASE_ORDER:
        sup_score = reliability
        sup_expl = f"PO inherits supplier reliability={reliability:.2f}."
    else:
        sup_score = 0.55
        sup_expl = "Limited supplier exposure."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.SUPPLIER_RELIABILITY,
            score=_clamp(sup_score),
            weight=1.0,
            explanation=sup_expl,
        )
    )
    risks.append(
        DecisionRisk(
            category=RiskCategory.SUPPLIER,
            level=_level(1.0 - reliability),
            score=_clamp(1.0 - reliability),
            explanation=f"Supplier risk from reliability={reliability:.2f}.",
        )
    )

    # Cost (higher = cheaper / better cost outcome)
    unit_cost = _f(recommendation.get("unit_cost") or recommendation.get("estimated_cost"))
    qty = _f(recommendation.get("recommended_quantity")) or 0.0
    if action in {DecisionAction.NO_ACTION, DecisionAction.DELAY_PURCHASE, DecisionAction.REJECT_RECOMMENDATION}:
        cost_score = 0.95
        cost_expl = "Avoids immediate purchase cost."
    elif action == DecisionAction.TRANSFER_INVENTORY:
        cost_score = 0.75
        cost_expl = "Transfer typically cheaper than new purchase."
    elif action == DecisionAction.SPLIT_ORDER:
        cost_score = 0.55
        cost_expl = "Split may increase logistics cost."
    elif action == DecisionAction.CREATE_PURCHASE_ORDER:
        cost_score = 0.4 if (unit_cost or 0) * qty > 5000 else 0.6
        cost_expl = "PO incurs full purchase cost."
    else:
        cost_score = 0.5
        cost_expl = "Neutral cost impact."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.COST,
            score=cost_score,
            weight=0.9,
            explanation=cost_expl,
        )
    )

    # Lead time (higher = faster availability)
    lead = _f(supplier.get("lead_time_days") or recommendation.get("lead_time_days")) or 5.0
    if action == DecisionAction.TRANSFER_INVENTORY:
        lead_score = 0.85
        lead_expl = "Transfer usually faster than supplier lead time."
    elif action == DecisionAction.CREATE_PURCHASE_ORDER:
        lead_score = _clamp(1.0 - min(lead, 20.0) / 20.0)
        lead_expl = f"PO constrained by lead_time_days={lead}."
    elif action == DecisionAction.DELAY_PURCHASE:
        lead_score = 0.2
        lead_expl = "Delay intentionally postpones availability."
    else:
        lead_score = 0.5
        lead_expl = "Neutral lead-time impact."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.LEAD_TIME,
            score=lead_score,
            weight=0.8,
            explanation=lead_expl,
        )
    )

    # Forecast confidence
    conf = _f(recommendation.get("forecast_confidence") or inventory.get("forecast_confidence"))
    if conf is None:
        conf = 0.55
        factors.append(
            DecisionFactor(
                name="forecast_confidence_defaulted",
                value=conf,
                explanation="Forecast confidence missing; neutral default used.",
            )
        )
    if action == DecisionAction.CREATE_PURCHASE_ORDER:
        fc_score = conf
        fc_expl = f"PO depends on forecast confidence={conf:.2f}."
    elif action in {DecisionAction.WAIT_FOR_HUMAN, DecisionAction.ESCALATE_APPROVAL} and conf < 0.5:
        fc_score = 0.85
        fc_expl = "Low forecast confidence favors human review."
    else:
        fc_score = 0.5 + 0.3 * conf
        fc_expl = "Moderate dependence on forecast."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.FORECAST_CONFIDENCE,
            score=_clamp(fc_score),
            weight=1.0,
            explanation=fc_expl,
        )
    )

    # Operational complexity (higher = simpler)
    complexity_map = {
        DecisionAction.NO_ACTION: 1.0,
        DecisionAction.WAIT_FOR_HUMAN: 0.7,
        DecisionAction.DELAY_PURCHASE: 0.8,
        DecisionAction.REJECT_RECOMMENDATION: 0.75,
        DecisionAction.CREATE_PURCHASE_ORDER: 0.55,
        DecisionAction.ESCALATE_APPROVAL: 0.5,
        DecisionAction.TRANSFER_INVENTORY: 0.4,
        DecisionAction.SPLIT_ORDER: 0.3,
        DecisionAction.CHANGE_SUPPLIER: 0.25,
    }
    op_score = complexity_map.get(action, 0.5)
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.OPERATIONAL_COMPLEXITY,
            score=op_score,
            weight=0.7,
            explanation=f"Operational simplicity score={op_score:.2f}.",
        )
    )

    # Historical success from memory counts
    mem = context.memory or {}
    hist_n = int(mem.get("retrieved_records") or 0)
    hist_score = _clamp(0.4 + min(hist_n, 10) * 0.05)
    if action in {DecisionAction.CREATE_PURCHASE_ORDER, DecisionAction.ESCALATE_APPROVAL}:
        hist_expl = f"Historical memory evidence count={hist_n}."
    else:
        hist_score = 0.5
        hist_expl = "Limited historical signal for this action."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.HISTORICAL_SUCCESS,
            score=hist_score,
            weight=0.8,
            explanation=hist_expl,
        )
    )

    # ERP risk (higher score = lower ERP risk)
    erp_failures = int(erp.get("recent_failures") or erp.get("failure_count") or 0)
    erp_risk = _clamp(min(erp_failures, 5) / 5.0)
    if action == DecisionAction.CREATE_PURCHASE_ORDER:
        erp_score = 1.0 - erp_risk
        erp_expl = f"PO transmission risk from recent_failures={erp_failures}."
    elif action in {DecisionAction.WAIT_FOR_HUMAN, DecisionAction.DELAY_PURCHASE} and erp_risk > 0.4:
        erp_score = 0.85
        erp_expl = "Avoiding ERP while failure rate is elevated."
    else:
        erp_score = 0.65
        erp_expl = "Limited ERP exposure."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.ERP_RISK,
            score=erp_score,
            weight=1.0,
            explanation=erp_expl,
        )
    )
    risks.append(
        DecisionRisk(
            category=RiskCategory.ERP,
            level=_level(erp_risk),
            score=erp_risk,
            explanation=f"ERP failure pressure={erp_risk:.2f}.",
        )
    )

    # Human approval impact (higher = better governance alignment)
    if policy.requires_human and action in {
        DecisionAction.ESCALATE_APPROVAL,
        DecisionAction.WAIT_FOR_HUMAN,
    }:
        human_score = 1.0
        human_expl = "Satisfies required human approval path."
    elif action == DecisionAction.CREATE_PURCHASE_ORDER and policy.requires_human:
        human_score = 0.1
        human_expl = "Would bypass required human approval."
    elif action in {DecisionAction.ESCALATE_APPROVAL, DecisionAction.WAIT_FOR_HUMAN}:
        human_score = 0.75
        human_expl = "Preserves human oversight."
    else:
        human_score = 0.55
        human_expl = "Standard governance impact."
    scores.append(
        DecisionScore(
            dimension=ScoreDimension.HUMAN_APPROVAL_IMPACT,
            score=human_score,
            weight=1.3,
            explanation=human_expl,
        )
    )
    if policy.requires_human:
        risks.append(
            DecisionRisk(
                category=RiskCategory.COMPLIANCE,
                level=RiskLevel.HIGH,
                score=0.75,
                explanation="Policy requires human review.",
            )
        )
        risks.append(
            DecisionRisk(
                category=RiskCategory.HUMAN,
                level=RiskLevel.MEDIUM,
                score=0.5,
                explanation="Human decision latency risk if escalated.",
            )
        )

    # Financial risk for high-value PO
    amount = (unit_cost or 0) * qty
    if amount >= 5000 and action == DecisionAction.CREATE_PURCHASE_ORDER:
        risks.append(
            DecisionRisk(
                category=RiskCategory.FINANCIAL,
                level=RiskLevel.HIGH,
                score=0.7,
                explanation=f"Estimated order value {amount:.0f} exceeds $5,000 threshold.",
            )
        )

    total = sum(s.weighted for s in scores) / max(sum(s.weight for s in scores), 1e-9)
    candidate.scores = scores
    candidate.risks = risks
    candidate.factors = factors
    candidate.total_score = round(total, 4)
    return candidate


def _f(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _level(risk_score: float) -> RiskLevel:
    if risk_score >= 0.85:
        return RiskLevel.CRITICAL
    if risk_score >= 0.65:
        return RiskLevel.HIGH
    if risk_score >= 0.35:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW

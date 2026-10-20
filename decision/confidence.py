"""Confidence model — never fabricate; default when evidence missing."""

from __future__ import annotations

from decision.contracts import (
    DecisionCandidate,
    DecisionConfidence,
    DecisionContext,
    DecisionFactor,
)


def compute_confidence(
    context: DecisionContext,
    winning: DecisionCandidate,
) -> DecisionConfidence:
    factors: list[DecisionFactor] = []
    missing: list[str] = []
    parts: list[float] = []

    mem = context.memory or {}
    mem_n = int(mem.get("retrieved_records") or 0)
    if mem_n > 0:
        mem_score = min(1.0, 0.4 + mem_n * 0.06)
        factors.append(
            DecisionFactor(
                name="memory_evidence",
                value=mem_n,
                explanation=f"{mem_n} structured memory records available.",
            )
        )
    else:
        mem_score = 0.35
        missing.append("structured_memory")
        factors.append(
            DecisionFactor(
                name="memory_evidence",
                value=0,
                explanation="No structured memory evidence; confidence reduced.",
            )
        )
    parts.append(mem_score)

    knowledge = context.semantic_knowledge or []
    if knowledge:
        kn_score = min(1.0, 0.45 + len(knowledge) * 0.1)
        factors.append(
            DecisionFactor(
                name="knowledge_evidence",
                value=len(knowledge),
                explanation=f"{len(knowledge)} semantic knowledge hits.",
            )
        )
    else:
        kn_score = 0.4
        missing.append("semantic_knowledge")
        factors.append(
            DecisionFactor(
                name="knowledge_evidence",
                value=0,
                explanation="No semantic knowledge retrieved.",
            )
        )
    parts.append(kn_score)

    policy = context.policy
    if policy.disposition or policy.policy_ids:
        pol_score = 0.9 if policy.hard_rule_applied else 0.75
        factors.append(
            DecisionFactor(
                name="policy_coverage",
                value=policy.disposition,
                explanation="Policy evaluation present.",
            )
        )
    else:
        pol_score = 0.45
        missing.append("policy_evaluation")
        factors.append(
            DecisionFactor(
                name="policy_coverage",
                value=None,
                explanation="Policy evaluation missing.",
            )
        )
    parts.append(pol_score)

    # Historical similarity proxy via memory ops / extras
    hist = context.extras.get("historical_similarity")
    if hist is None:
        hist_score = 0.5
        missing.append("historical_similarity")
    else:
        try:
            hist_score = max(0.0, min(1.0, float(hist)))
        except (TypeError, ValueError):
            hist_score = 0.5
            missing.append("historical_similarity")
    parts.append(hist_score)
    factors.append(
        DecisionFactor(
            name="historical_similarity",
            value=hist_score,
            explanation="Historical similarity contribution.",
        )
    )

    # Inventory / recommendation completeness
    if not context.inventory:
        missing.append("inventory")
        parts.append(0.4)
    else:
        parts.append(0.8)
    if not context.recommendation:
        missing.append("recommendation")
        parts.append(0.4)
    else:
        parts.append(0.8)

    # Spread vs next-best candidate lowers confidence when close race
    score = sum(parts) / len(parts)
    # Winning eligibility / score quality
    if not winning.eligible:
        score *= 0.5
        factors.append(
            DecisionFactor(
                name="winning_ineligible",
                value=False,
                explanation="Winning candidate marked ineligible — confidence halved.",
            )
        )
    score = max(0.05, min(0.98, score))

    if score >= 0.75:
        level = "high"
    elif score >= 0.5:
        level = "medium"
    else:
        level = "low"

    return DecisionConfidence(
        score=round(score, 4),
        level=level,
        factors=factors,
        missing_data=missing,
        explanation=(
            f"Confidence {level} ({score:.2f}) from memory, knowledge, policy, "
            f"and data completeness; missing={missing or ['none']}."
        ),
    )

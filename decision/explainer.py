"""Decision explainer — human-readable outcome narrative."""

from __future__ import annotations

from decision.contracts import (
    DecisionAlternative,
    DecisionCandidate,
    DecisionConfidence,
    DecisionContext,
    DecisionExplanation,
    DecisionFactor,
)
from decision.types import ACTION_LABELS


def build_explanation(
    *,
    context: DecisionContext,
    winning: DecisionCandidate,
    candidates: list[DecisionCandidate],
    confidence: DecisionConfidence,
    llm_summary: str | None = None,
) -> DecisionExplanation:
    rejected: list[DecisionAlternative] = []
    for cand in candidates:
        if cand.candidate_id == winning.candidate_id:
            continue
        reason = cand.ineligibility_reason or (
            f"Lower total score ({cand.total_score:.3f}) vs winner ({winning.total_score:.3f})."
        )
        trade_offs = [
            s.explanation
            for s in cand.scores[:3]
            if s.explanation
        ]
        rejected.append(
            DecisionAlternative(
                candidate_id=cand.candidate_id,
                action=cand.action,
                label=cand.label or ACTION_LABELS.get(str(cand.action), str(cand.action)),
                total_score=cand.total_score,
                rejection_reason=reason,
                trade_offs=trade_offs,
            )
        )

    factors = list(winning.factors)
    for s in winning.scores:
        factors.append(
            DecisionFactor(
                name=str(s.dimension),
                value=s.score,
                weight=s.weight,
                explanation=s.explanation,
            )
        )

    memory_refs: list[str] = []
    mem = context.memory or {}
    for key in ("knowledge_sources", "citations", "record_ids"):
        val = mem.get(key)
        if isinstance(val, list):
            memory_refs.extend(str(x) for x in val if x)

    knowledge_refs: list[str] = []
    for item in context.semantic_knowledge or []:
        cite = item.get("citation") or item.get("document_id") or item.get("source_reference")
        if cite:
            knowledge_refs.append(str(cite))

    policy_refs = list(context.policy.policy_ids)
    if context.policy.disposition:
        policy_refs.append(f"disposition:{context.policy.disposition}")

    evidence = []
    if context.recommendation_id:
        evidence.append(f"recommendation:{context.recommendation_id}")
    if context.store_id and context.sku:
        evidence.append(f"store_sku:{context.store_id}/{context.sku}")
    evidence.extend(policy_refs[:3])
    evidence.extend(knowledge_refs[:3])

    trade_offs = [
        f"Selected {winning.label} (score={winning.total_score:.3f}).",
    ]
    if rejected:
        top = max(rejected, key=lambda a: a.total_score)
        trade_offs.append(
            f"Next alternative {top.label} scored {top.total_score:.3f}: {top.rejection_reason}"
        )

    label = winning.label or ACTION_LABELS.get(str(winning.action), str(winning.action))
    narrative = (
        f"Decision engine selected '{label}' using available policy, inventory, "
        f"memory, and knowledge signals. Confidence={confidence.level} "
        f"({confidence.score:.2f})."
    )
    if llm_summary:
        narrative = f"{narrative} Advisor note: {llm_summary}"

    return DecisionExplanation(
        chosen_action=str(winning.action),
        chosen_label=label,
        rejected_alternatives=rejected,
        decision_factors=factors,
        trade_offs=trade_offs,
        confidence=confidence,
        evidence=evidence,
        policy_references=policy_refs,
        memory_references=memory_refs,
        knowledge_references=knowledge_refs,
        llm_summary=llm_summary,
        narrative=narrative,
    )

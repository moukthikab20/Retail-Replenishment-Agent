"""Decision Engine — evaluate candidates before execution."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from decision.audit import (
    AUDIT_CANDIDATE_GENERATED,
    AUDIT_CANDIDATE_SCORED,
    AUDIT_DECISION_ESCALATED,
    AUDIT_DECISION_FAILED,
    AUDIT_DECISION_SELECTED,
    AUDIT_DECISION_STARTED,
    record_decision_event,
)
from decision.candidates import generate_candidates
from decision.confidence import compute_confidence
from decision.contracts import (
    DecisionCandidate,
    DecisionContext,
    DecisionOutcome,
    DecisionRecommendation,
    DecisionTrace,
)
from decision.explainer import build_explanation
from decision.scoring import score_candidate
from decision.strategies import get_strategy
from decision.types import ACTION_LABELS, DecisionAction, DecisionStatus
from decision.validators import apply_policy_precedence, should_escalate
from decision.advisor import advise_on_decision

logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    Reasons over multiple candidate business actions.
    Does not mutate business state or execute ERP / approvals.
    """

    def __init__(
        self,
        *,
        strategy_name: str,
        llm_advisor_enabled: bool = False,
        confidence_floor: float = 0.45,
        risk_ceiling: float = 0.75,
    ) -> None:
        self.strategy_name = strategy_name
        self.llm_advisor_enabled = llm_advisor_enabled
        self.confidence_floor = confidence_floor
        self.risk_ceiling = risk_ceiling
        self._strategy = get_strategy(strategy_name)

    def evaluate(self, context: DecisionContext) -> DecisionOutcome:
        started = time.perf_counter()
        events: list[dict[str, Any]] = []
        evaluation_id = context.evaluation_id

        def _evt(event_type: str, details: dict[str, Any] | None = None) -> None:
            events.append(
                record_decision_event(
                    event_type,
                    evaluation_id=evaluation_id,
                    execution_id=context.execution_id,
                    details=details,
                )
            )

        try:
            _evt(AUDIT_DECISION_STARTED, {"strategy": self.strategy_name})

            # Policy hard rules are already on context.policy (from business policy).
            candidates = generate_candidates(context)
            candidates = apply_policy_precedence(candidates, context)
            _evt(
                AUDIT_CANDIDATE_GENERATED,
                {
                    "count": len(candidates),
                    "actions": [str(c.action) for c in candidates],
                },
            )

            scored: list[DecisionCandidate] = [
                score_candidate(c, context) for c in candidates
            ]
            _evt(
                AUDIT_CANDIDATE_SCORED,
                {
                    "scores": [
                        {"id": c.candidate_id, "action": str(c.action), "total": c.total_score}
                        for c in scored
                    ]
                },
            )

            winning = self._strategy.select(scored, context)
            confidence = compute_confidence(context, winning)
            max_risk = max((float(r.score) for r in winning.risks), default=0.0)

            escalate = should_escalate(
                winning=winning,
                confidence_score=confidence.score,
                max_risk=max_risk,
                confidence_floor=self.confidence_floor,
                risk_ceiling=self.risk_ceiling,
                policy=context.policy,
            )

            # If escalation required but winner is an execute action, force wait/escalate.
            if escalate and str(winning.action) == DecisionAction.CREATE_PURCHASE_ORDER:
                for preferred in (
                    DecisionAction.ESCALATE_APPROVAL,
                    DecisionAction.WAIT_FOR_HUMAN,
                ):
                    match = next(
                        (c for c in scored if str(c.action) == preferred and c.eligible),
                        None,
                    )
                    if match:
                        winning = match
                        break

            advisor = advise_on_decision(
                context=context,
                winning=winning,
                candidates=scored,
                enabled=self.llm_advisor_enabled,
            )
            # Advisor must never change the winner.
            llm_summary = advisor.get("summary") if advisor.get("involved") else None

            explanation = build_explanation(
                context=context,
                winning=winning,
                candidates=scored,
                confidence=confidence,
                llm_summary=llm_summary,
            )

            require_human = escalate or str(winning.action) in {
                DecisionAction.WAIT_FOR_HUMAN,
                DecisionAction.ESCALATE_APPROVAL,
            }
            execute = (not require_human) and str(winning.action) in {
                DecisionAction.CREATE_PURCHASE_ORDER,
                DecisionAction.TRANSFER_INVENTORY,
                DecisionAction.SPLIT_ORDER,
                DecisionAction.CHANGE_SUPPLIER,
                DecisionAction.DELAY_PURCHASE,
                DecisionAction.REJECT_RECOMMENDATION,
                DecisionAction.NO_ACTION,
            }
            # Engine recommends only — never executes.
            recommendation = DecisionRecommendation(
                action=winning.action,
                label=winning.label or ACTION_LABELS.get(str(winning.action), str(winning.action)),
                require_human=require_human,
                execute=False,  # Decision Engine never executes business actions
                rationale=explanation.narrative,
                candidate_id=winning.candidate_id,
            )

            status = (
                DecisionStatus.ESCALATED if require_human else DecisionStatus.SELECTED
            )
            if require_human:
                _evt(
                    AUDIT_DECISION_ESCALATED,
                    {
                        "action": str(winning.action),
                        "confidence": confidence.score,
                        "max_risk": max_risk,
                    },
                )
            else:
                _evt(
                    AUDIT_DECISION_SELECTED,
                    {"action": str(winning.action), "candidate_id": winning.candidate_id},
                )

            duration = (time.perf_counter() - started) * 1000.0
            memory_ids = list(explanation.memory_references)
            knowledge_ids = [
                str(k.get("document_id") or k.get("citation") or "")
                for k in (context.semantic_knowledge or [])
                if k
            ]
            knowledge_ids = [k for k in knowledge_ids if k] or list(
                explanation.knowledge_references
            )

            trace = DecisionTrace(
                evaluation_id=evaluation_id,
                execution_id=context.execution_id,
                strategy=self.strategy_name,
                candidate_scores=[
                    {
                        "candidate_id": c.candidate_id,
                        "action": str(c.action),
                        "total_score": c.total_score,
                        "eligible": c.eligible,
                        "scores": [
                            {
                                "dimension": str(s.dimension),
                                "score": s.score,
                                "weight": s.weight,
                                "explanation": s.explanation,
                            }
                            for s in c.scores
                        ],
                    }
                    for c in scored
                ],
                winning_candidate_id=winning.candidate_id,
                rejected_candidate_ids=[
                    c.candidate_id for c in scored if c.candidate_id != winning.candidate_id
                ],
                policy_factors=list(explanation.policy_references),
                memory_ids=memory_ids,
                knowledge_ids=knowledge_ids,
                llm_involved=bool(advisor.get("involved")),
                events=events,
                created_at=datetime.now(timezone.utc),
            )

            return DecisionOutcome(
                evaluation_id=evaluation_id,
                status=status,
                recommendation=recommendation,
                winning_candidate=winning,
                alternatives=explanation.rejected_alternatives,
                explanation=explanation,
                confidence=confidence,
                risks=list(winning.risks),
                policy=context.policy,
                trace=trace,
                llm_advisor=advisor,
                strategy=self.strategy_name,
                duration_ms=duration,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision_evaluate_failed err=%s", exc)
            _evt(AUDIT_DECISION_FAILED, {"error": type(exc).__name__})
            duration = (time.perf_counter() - started) * 1000.0
            fallback = DecisionCandidate(
                candidate_id="CAND-FALLBACK",
                action=DecisionAction.WAIT_FOR_HUMAN,
                label=ACTION_LABELS[DecisionAction.WAIT_FOR_HUMAN],
                description="Fail-soft fallback — scoring failed.",
                total_score=0.0,
            )
            confidence = compute_confidence(context, fallback)
            explanation = build_explanation(
                context=context,
                winning=fallback,
                candidates=[fallback],
                confidence=confidence,
            )
            return DecisionOutcome(
                evaluation_id=evaluation_id,
                status=DecisionStatus.DEGRADED,
                recommendation=DecisionRecommendation(
                    action=DecisionAction.WAIT_FOR_HUMAN,
                    label=ACTION_LABELS[DecisionAction.WAIT_FOR_HUMAN],
                    require_human=True,
                    execute=False,
                    rationale="Decision scoring failed; defaulting to human path.",
                    candidate_id=fallback.candidate_id,
                ),
                winning_candidate=fallback,
                alternatives=[],
                explanation=explanation,
                confidence=confidence,
                risks=[],
                policy=context.policy,
                trace=DecisionTrace(
                    evaluation_id=evaluation_id,
                    execution_id=context.execution_id,
                    strategy=self.strategy_name,
                    llm_involved=False,
                    events=events,
                    created_at=datetime.now(timezone.utc),
                ),
                strategy=self.strategy_name,
                duration_ms=duration,
                degraded=True,
                degradation_reason=type(exc).__name__,
            )

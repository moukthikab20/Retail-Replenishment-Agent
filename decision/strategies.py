"""Decision strategies — select winning candidate."""

from __future__ import annotations

from typing import Protocol

from decision.contracts import DecisionCandidate, DecisionContext
from decision.types import DecisionAction, DecisionStrategyName, ScoreDimension


class DecisionStrategy(Protocol):
    name: str

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        ...


def _eligible(candidates: list[DecisionCandidate]) -> list[DecisionCandidate]:
    return [c for c in candidates if c.eligible]


def _score_for(candidate: DecisionCandidate, dimension: ScoreDimension) -> float:
    for s in candidate.scores:
        if str(s.dimension) == str(dimension):
            return float(s.score)
    return 0.0


def _max_risk(candidate: DecisionCandidate) -> float:
    if not candidate.risks:
        return 0.0
    return max(float(r.score) for r in candidate.risks)


class BalancedStrategy:
    name = DecisionStrategyName.BALANCED.value

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        pool = _eligible(candidates) or candidates
        return max(pool, key=lambda c: c.total_score)


class LowestRiskStrategy:
    name = DecisionStrategyName.LOWEST_RISK.value

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        pool = _eligible(candidates) or candidates
        return min(pool, key=lambda c: (_max_risk(c), -c.total_score))


class LowestCostStrategy:
    name = DecisionStrategyName.LOWEST_COST.value

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        pool = _eligible(candidates) or candidates
        return max(pool, key=lambda c: (_score_for(c, ScoreDimension.COST), c.total_score))


class FastestDeliveryStrategy:
    name = DecisionStrategyName.FASTEST_DELIVERY.value

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        pool = _eligible(candidates) or candidates
        return max(
            pool,
            key=lambda c: (_score_for(c, ScoreDimension.LEAD_TIME), c.total_score),
        )


class BusinessPolicyFirstStrategy:
    name = DecisionStrategyName.BUSINESS_POLICY_FIRST.value

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        pool = _eligible(candidates) or candidates
        # Prefer highest policy compliance, then total
        return max(
            pool,
            key=lambda c: (
                _score_for(c, ScoreDimension.POLICY_COMPLIANCE),
                _score_for(c, ScoreDimension.HUMAN_APPROVAL_IMPACT),
                c.total_score,
            ),
        )


class MockStrategy:
    """Deterministic demo strategy — prefers escalate when policy requires human else PO."""

    name = DecisionStrategyName.MOCK.value

    def select(
        self, candidates: list[DecisionCandidate], context: DecisionContext
    ) -> DecisionCandidate:
        pool = _eligible(candidates) or candidates
        by_action = {str(c.action): c for c in pool}
        if context.policy.requires_human or context.policy.blocked:
            for action in (
                DecisionAction.ESCALATE_APPROVAL,
                DecisionAction.WAIT_FOR_HUMAN,
                DecisionAction.REJECT_RECOMMENDATION,
            ):
                if action.value in by_action:
                    return by_action[action.value]
        if DecisionAction.CREATE_PURCHASE_ORDER.value in by_action:
            return by_action[DecisionAction.CREATE_PURCHASE_ORDER.value]
        return max(pool, key=lambda c: c.total_score)


STRATEGIES: dict[str, type] = {
    DecisionStrategyName.LOWEST_RISK.value: LowestRiskStrategy,
    DecisionStrategyName.LOWEST_COST.value: LowestCostStrategy,
    DecisionStrategyName.FASTEST_DELIVERY.value: FastestDeliveryStrategy,
    DecisionStrategyName.BALANCED.value: BalancedStrategy,
    DecisionStrategyName.BUSINESS_POLICY_FIRST.value: BusinessPolicyFirstStrategy,
    DecisionStrategyName.MOCK.value: MockStrategy,
}


def get_strategy(name: str) -> DecisionStrategy:
    key = (name or "").strip().lower()
    if key not in STRATEGIES:
        from integrations.failures import ProviderConfigError

        available = ", ".join(sorted(STRATEGIES))
        raise ProviderConfigError(
            f"Decision strategy '{key}' is not available. Supported: {available}.",
            provider_key="decision",
        )
    return STRATEGIES[key]()

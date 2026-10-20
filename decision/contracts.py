"""Decision Intelligence typed contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from decision.types import (
    ACTION_LABELS,
    DecisionAction,
    DecisionStatus,
    DecisionStrategyName,
    RiskCategory,
    RiskLevel,
    ScoreDimension,
)


def new_evaluation_id() -> str:
    return f"DEC-{uuid4().hex[:12].upper()}"


class DecisionFactor(BaseModel):
    name: str
    value: float | str | bool | None = None
    weight: float = 1.0
    explanation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class DecisionScore(BaseModel):
    dimension: ScoreDimension | str
    score: float  # 0..1 higher is better for that dimension's preferred polarity
    weight: float = 1.0
    explanation: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def weighted(self) -> float:
        return float(self.score) * float(self.weight)


class DecisionRisk(BaseModel):
    category: RiskCategory | str
    level: RiskLevel | str
    score: float = 0.0  # 0..1 higher = more risk
    explanation: str = ""


class DecisionConfidence(BaseModel):
    score: float  # 0..1
    level: str = "medium"  # low | medium | high
    factors: list[DecisionFactor] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    explanation: str = ""


class DecisionPolicyResult(BaseModel):
    disposition: str | None = None
    requires_human: bool = False
    blocked: bool = False
    policy_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    hard_rule_applied: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class DecisionCandidate(BaseModel):
    candidate_id: str
    action: DecisionAction | str
    label: str = ""
    description: str = ""
    scores: list[DecisionScore] = Field(default_factory=list)
    risks: list[DecisionRisk] = Field(default_factory=list)
    factors: list[DecisionFactor] = Field(default_factory=list)
    total_score: float = 0.0
    eligible: bool = True
    ineligibility_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def ensure_label(self) -> "DecisionCandidate":
        if not self.label:
            self.label = ACTION_LABELS.get(str(self.action), str(self.action))
        return self


class DecisionAlternative(BaseModel):
    candidate_id: str
    action: DecisionAction | str
    label: str = ""
    total_score: float = 0.0
    rejection_reason: str = ""
    trade_offs: list[str] = Field(default_factory=list)


class DecisionExplanation(BaseModel):
    chosen_action: str
    chosen_label: str = ""
    rejected_alternatives: list[DecisionAlternative] = Field(default_factory=list)
    decision_factors: list[DecisionFactor] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    confidence: DecisionConfidence | None = None
    evidence: list[str] = Field(default_factory=list)
    policy_references: list[str] = Field(default_factory=list)
    memory_references: list[str] = Field(default_factory=list)
    knowledge_references: list[str] = Field(default_factory=list)
    llm_summary: str | None = None
    narrative: str = ""


class DecisionRecommendation(BaseModel):
    action: DecisionAction | str
    label: str = ""
    require_human: bool = False
    execute: bool = False
    rationale: str = ""
    candidate_id: str | None = None


class DecisionTrace(BaseModel):
    evaluation_id: str
    execution_id: str | None = None
    strategy: str
    candidate_scores: list[dict[str, Any]] = Field(default_factory=list)
    winning_candidate_id: str | None = None
    rejected_candidate_ids: list[str] = Field(default_factory=list)
    policy_factors: list[str] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    llm_involved: bool = False
    events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None


class DecisionContext(BaseModel):
    """Read-only assembly of signals for evaluation — never mutates business state."""

    evaluation_id: str = Field(default_factory=new_evaluation_id)
    execution_id: str | None = None
    goal: str | None = None
    workflow: str | None = None
    planner_objective: str | None = None
    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    purchase_order_id: str | None = None
    actor: str | None = None
    actor_role: str | None = None
    recommendation: dict[str, Any] = Field(default_factory=dict)
    inventory: dict[str, Any] = Field(default_factory=dict)
    supplier_history: dict[str, Any] = Field(default_factory=dict)
    policy: DecisionPolicyResult = Field(default_factory=DecisionPolicyResult)
    memory: dict[str, Any] = Field(default_factory=dict)
    semantic_knowledge: list[dict[str, Any]] = Field(default_factory=list)
    erp_state: dict[str, Any] = Field(default_factory=dict)
    execution_history: list[dict[str, Any]] = Field(default_factory=list)
    human_approvals: list[dict[str, Any]] = Field(default_factory=list)
    conversation_context: str | None = None
    identity: dict[str, Any] = Field(default_factory=dict)
    business_context: dict[str, Any] = Field(default_factory=dict)
    extras: dict[str, Any] = Field(default_factory=dict)


class DecisionEvaluation(BaseModel):
    evaluation_id: str
    context: DecisionContext
    candidates: list[DecisionCandidate] = Field(default_factory=list)
    strategy: str = DecisionStrategyName.BALANCED.value
    status: DecisionStatus | str = DecisionStatus.EVALUATED
    duration_ms: float = 0.0
    degraded: bool = False
    degradation_reason: str | None = None


class DecisionOutcome(BaseModel):
    evaluation_id: str
    status: DecisionStatus | str = DecisionStatus.SELECTED
    recommendation: DecisionRecommendation
    winning_candidate: DecisionCandidate | None = None
    alternatives: list[DecisionAlternative] = Field(default_factory=list)
    explanation: DecisionExplanation
    confidence: DecisionConfidence
    risks: list[DecisionRisk] = Field(default_factory=list)
    policy: DecisionPolicyResult = Field(default_factory=DecisionPolicyResult)
    trace: DecisionTrace
    llm_advisor: dict[str, Any] = Field(default_factory=dict)
    strategy: str = DecisionStrategyName.BALANCED.value
    duration_ms: float = 0.0
    degraded: bool = False
    degradation_reason: str | None = None

    def to_ops_summary(self) -> dict[str, Any]:
        win = self.winning_candidate
        return {
            "evaluation_id": self.evaluation_id,
            "status": str(self.status),
            "strategy": self.strategy,
            "winning_action": str(self.recommendation.action),
            "winning_label": self.recommendation.label
            or ACTION_LABELS.get(str(self.recommendation.action), ""),
            "require_human": bool(self.recommendation.require_human),
            "execute": bool(self.recommendation.execute),
            "confidence": {
                "score": self.confidence.score,
                "level": self.confidence.level,
                "missing_data": list(self.confidence.missing_data),
                "explanation": self.confidence.explanation,
            },
            "risks": [
                {
                    "category": str(r.category),
                    "level": str(r.level),
                    "score": r.score,
                    "explanation": r.explanation,
                }
                for r in self.risks
            ],
            "alternatives": [
                {
                    "candidate_id": a.candidate_id,
                    "action": str(a.action),
                    "label": a.label,
                    "total_score": a.total_score,
                    "rejection_reason": a.rejection_reason,
                    "trade_offs": list(a.trade_offs),
                }
                for a in self.alternatives
            ],
            "policy_references": list(self.explanation.policy_references),
            "memory_references": list(self.explanation.memory_references),
            "knowledge_references": list(self.explanation.knowledge_references),
            "llm_involved": bool(self.trace.llm_involved),
            "llm_summary": self.explanation.llm_summary,
            "narrative": self.explanation.narrative,
            "candidate_scores": list(self.trace.candidate_scores),
            "timeline": list(self.trace.events),
            "duration_ms": round(self.duration_ms, 2),
            "degraded": self.degraded,
            "degradation_reason": self.degradation_reason,
            "winning_candidate_id": win.candidate_id if win else None,
            "evidence": list(self.explanation.evidence),
            "trade_offs": list(self.explanation.trade_offs),
        }

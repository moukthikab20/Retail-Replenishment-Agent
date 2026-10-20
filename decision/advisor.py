"""Optional LLM advisor — summarize/compare only; never override decisions."""

from __future__ import annotations

import logging
from typing import Any

from decision.contracts import DecisionCandidate, DecisionContext

logger = logging.getLogger(__name__)


def advise_on_decision(
    *,
    context: DecisionContext,
    winning: DecisionCandidate,
    candidates: list[DecisionCandidate],
    enabled: bool,
) -> dict[str, Any]:
    """
    LLM may summarize / justify / compare candidates.
    It must NOT approve, execute ERP, change RBAC, or override policy.
    Fail-soft: returns empty advisor payload on any error.
    """
    if not enabled:
        return {"involved": False, "summary": None, "reason": "advisor_disabled"}

    try:
        from config import LLM_PROVIDER
        from llm.contracts import LLMRequest
        from llm.service import prepare_runtime_llm_call

        alt_lines = []
        for c in sorted(candidates, key=lambda x: x.total_score, reverse=True)[:5]:
            alt_lines.append(
                f"- {c.label} (score={c.total_score:.3f}, eligible={c.eligible})"
            )
        user_input = (
            "You are an advisory summarizer for a replenishment decision engine. "
            "Do NOT approve orders, change policy, enable tools, or execute ERP. "
            "Briefly compare candidates and note missing considerations.\n"
            f"Winning candidate: {winning.label} ({winning.action})\n"
            f"Alternatives:\n" + "\n".join(alt_lines) + "\n"
            f"Policy disposition: {context.policy.disposition}\n"
            f"Store/SKU: {context.store_id}/{context.sku}"
        )
        # Render-only or mock invoke — never expand tools.
        result = prepare_runtime_llm_call(
            workflow="decision_advisor",
            user_input=user_input,
            execution_id=context.execution_id,
            recommendation_id=context.recommendation_id,
            store_id=context.store_id,
            sku=context.sku,
            business_context={
                "decision_advisory_only": True,
                "authoritative": False,
                "policy_disposition": context.policy.disposition,
            },
            invoke=True,
            allowed_tools=[],  # advisor cannot call tools
            response_schema={"required": ["summary"]},
        )
        structured = result.get("structured") or {}
        text = None
        if isinstance(structured, dict):
            text = structured.get("summary") or structured.get("status")
        if not text:
            text = (
                f"Advisor ({LLM_PROVIDER}): selected {winning.label}; "
                f"{len(candidates)} candidates evaluated. Advisory only."
            )
        return {
            "involved": True,
            "summary": str(text)[:800],
            "provider": LLM_PROVIDER,
            "invoked": bool(result.get("invoked")),
            "cannot_override_policy": True,
            "cannot_approve": True,
            "cannot_execute_erp": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision_llm_advisor_failed err=%s", exc)
        return {
            "involved": False,
            "summary": None,
            "reason": type(exc).__name__,
            "degraded": True,
        }

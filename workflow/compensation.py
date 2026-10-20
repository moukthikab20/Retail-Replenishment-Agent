"""Compensation metadata — explicit and service-backed only."""

from __future__ import annotations

from workflow.contracts import WorkflowCompensation, WorkflowStepExecution
from workflow.types import CompensationKind


# Actions that may be compensated locally (pre-ERP / draft).
_COMPENSATABLE_TOOLS = {
    "create_recommendation_record": "recommendation_soft_cancel",
}

# Never invent rollback for irreversible external effects.
_NOT_SAFE_TOOLS = {
    "create_mock_purchase_order",
    "transmit_order",
    "transmit_order_intent",
}


def compensation_for_step(step: WorkflowStepExecution) -> WorkflowCompensation:
    tool = (step.tool_name or "").strip()
    step_type = (step.step_type or "").lower()
    if tool in _NOT_SAFE_TOOLS or step_type == "erp":
        return WorkflowCompensation(
            kind=CompensationKind.NOT_SAFE,
            step_id=step.step_id,
            compensatable=False,
            reason="ERP/external acknowledgement or irreversible supplier action cannot be safely rolled back.",
        )
    if tool in _COMPENSATABLE_TOOLS:
        return WorkflowCompensation(
            kind=CompensationKind.EXPLICIT,
            step_id=step.step_id,
            compensatable=True,
            reason="Local/draft record may be cancelled via business service when configured.",
            service_action=_COMPENSATABLE_TOOLS[tool],
        )
    if step_type in {"approval", "human", "wait"}:
        return WorkflowCompensation(
            kind=CompensationKind.NONE,
            step_id=step.step_id,
            compensatable=False,
            reason="Waiting/approval steps leave no mutating side effect to reverse.",
        )
    return WorkflowCompensation(
        kind=CompensationKind.NONE,
        step_id=step.step_id,
        compensatable=False,
        reason="No explicit compensation configured.",
    )


def run_compensation_if_configured(
    step: WorkflowStepExecution,
    *,
    enabled: bool,
) -> WorkflowCompensation:
    """
    Coordinate compensation metadata only.
    Does not invent ERP rollback. Returns updated compensation record.
    """
    comp = compensation_for_step(step)
    if not enabled:
        comp.reason = (comp.reason or "") + " Compensation disabled by configuration."
        return comp
    if not comp.compensatable:
        return comp
    # Explicit hook point — business services own mutation; we only mark compensated.
    # No automatic destructive deletes in this POC.
    return WorkflowCompensation(
        kind=CompensationKind.EXPLICIT,
        step_id=step.step_id,
        compensatable=True,
        reason="Compensation marked complete (service-backed metadata; no invented ERP rollback).",
        service_action=comp.service_action,
        metadata={"status": "compensated_metadata_only"},
    )

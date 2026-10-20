"""Optional integration hooks — fail-soft, no business redesign."""

from __future__ import annotations

import logging

from eventbus.contracts import EventEnvelope
from eventbus.events import EventType

logger = logging.getLogger(__name__)


def maybe_resume_workflow_from_event(event: EventEnvelope) -> dict | None:
    """
    When approval/ERP acknowledgement arrives, record a resume request.
    Actual resume still goes through existing workflow/HITL APIs when ids are present.
    """
    execution_id = event.payload.get("execution_id") or event.correlation_id
    resolve_step_id = event.payload.get("resolve_step_id")
    if not execution_id:
        return {"resumed": False, "reason": "missing_execution_id"}

    # Publish a normalized resume-requested signal for ops/tests.
    if event.event_type != EventType.WORKFLOW_RESUME_REQUESTED:
        try:
            from eventbus.publisher import safe_publish

            safe_publish(
                EventType.WORKFLOW_RESUME_REQUESTED,
                aggregate_type="workflow",
                aggregate_id=str(event.payload.get("workflow_id") or execution_id),
                payload={
                    "execution_id": execution_id,
                    "resolve_step_id": resolve_step_id,
                    "source_event": event.event_type,
                    "source_event_id": event.event_id,
                },
                correlation_id=event.correlation_id or execution_id,
                actor=event.actor,
                metadata={"idempotency_key": f"resume-req:{execution_id}:{event.event_id}"},
            )
        except Exception:  # noqa: BLE001
            pass

    # Attempt soft merge into execution context if run exists.
    try:
        from agent.execution_engine import get_execution, merge_execution_context_fields

        ex = get_execution(str(execution_id))
        if ex is None:
            return {"resumed": False, "reason": "execution_not_found"}
        merge_execution_context_fields(
            str(execution_id),
            {
                "event_resume": {
                    "event_type": event.event_type,
                    "event_id": event.event_id,
                    "resolve_step_id": resolve_step_id,
                    "aggregate_id": event.aggregate_id,
                }
            },
        )
        return {"resumed": True, "execution_id": execution_id, "soft": True}
    except Exception as exc:  # noqa: BLE001
        logger.debug("maybe_resume_workflow_from_event err=%s", exc)
        return {"resumed": False, "reason": type(exc).__name__}

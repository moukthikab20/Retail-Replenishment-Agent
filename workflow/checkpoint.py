"""Durable checkpoint helpers — persisted in AgentRunStateRow.state_json context."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from workflow.contracts import WorkflowCheckpoint, WorkflowExecution


def checkpoint_from_workflow(workflow: WorkflowExecution) -> WorkflowCheckpoint:
    now = datetime.now(timezone.utc)
    if workflow.checkpoint is None:
        from workflow.contracts import new_checkpoint_id

        workflow.checkpoint = WorkflowCheckpoint(
            checkpoint_id=new_checkpoint_id(),
            workflow_id=workflow.workflow_id,
            execution_id=workflow.execution_id,
            plan_id=workflow.plan_id,
        )
    ckp = workflow.checkpoint
    ckp.status = workflow.status
    ckp.execution_id = workflow.execution_id
    ckp.plan_id = workflow.plan_id
    ckp.completed_steps = [
        s.step_id for s in workflow.steps if str(s.status) == "succeeded"
    ]
    ckp.failed_steps = [s.step_id for s in workflow.steps if str(s.status) == "failed"]
    ckp.waiting_steps = [s.step_id for s in workflow.steps if str(s.status) == "waiting"]
    ckp.current_step = next(
        (
            s.step_id
            for s in workflow.steps
            if str(s.status) in {"running", "waiting", "ready", "retry_pending"}
        ),
        ckp.completed_steps[-1] if ckp.completed_steps else None,
    )
    ckp.step_outputs = {
        s.step_id: dict(s.output_summary) for s in workflow.steps if s.output_summary
    }
    ckp.version = workflow.version
    ckp.updated_at = now
    if ckp.created_at is None:
        ckp.created_at = now
    return ckp


def persist_workflow_to_context(
    context: dict[str, Any] | None, workflow: WorkflowExecution
) -> dict[str, Any]:
    base = dict(context or {})
    checkpoint_from_workflow(workflow)
    base["workflow_ops"] = workflow.to_ops_summary()
    base["workflow_id"] = workflow.workflow_id
    base["workflow_checkpoint"] = (
        workflow.checkpoint.model_dump(mode="json") if workflow.checkpoint else None
    )
    return base


def load_workflow_from_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    data = dict(context or {})
    return data.get("workflow_ops") if isinstance(data.get("workflow_ops"), dict) else None

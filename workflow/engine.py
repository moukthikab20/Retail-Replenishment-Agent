"""Workflow Execution Engine — coordinates planner execution durably."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from planner.contracts import Plan
from planner.types import ExecutionState, PlanStepStatus
from workflow.adapter import refresh_from_plan, workflow_from_plan
from workflow.audit import (
    AUDIT_WORKFLOW_CANCELLED,
    AUDIT_WORKFLOW_COMPLETED,
    AUDIT_WORKFLOW_COMPENSATION_COMPLETED,
    AUDIT_WORKFLOW_COMPENSATION_STARTED,
    AUDIT_WORKFLOW_CREATED,
    AUDIT_WORKFLOW_FAILED,
    AUDIT_WORKFLOW_RESUMED,
    AUDIT_WORKFLOW_RETRY_SCHEDULED,
    AUDIT_WORKFLOW_STARTED,
    AUDIT_WORKFLOW_STEP_COMPLETED,
    AUDIT_WORKFLOW_STEP_FAILED,
    AUDIT_WORKFLOW_STEP_STARTED,
    AUDIT_WORKFLOW_WAITING,
    record_workflow_event,
)
from workflow.checkpoint import checkpoint_from_workflow, persist_workflow_to_context
from workflow.compensation import run_compensation_if_configured
from workflow.contracts import (
    WorkflowExecution,
    WorkflowExecutionResult,
    WorkflowFailure,
    WorkflowResumeRequest,
    WorkflowRetryPolicy,
)
from workflow.retry import next_delay_seconds, should_retry
from workflow.states import assert_transition
from workflow.types import FailureClass, WorkflowStatus, WorkflowStepStatus

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Owns execution coordination over an existing planner Plan.
    Does not own business rules or business data mutation.
    """

    def __init__(
        self,
        *,
        max_parallel: int = 4,
        default_timeout_seconds: float = 120.0,
        retry_limit: int = 3,
        checkpoints_enabled: bool = True,
        compensation_enabled: bool = False,
    ) -> None:
        self.max_parallel = max_parallel
        self.default_timeout_seconds = default_timeout_seconds
        self.retry_limit = retry_limit
        self.checkpoints_enabled = checkpoints_enabled
        self.compensation_enabled = compensation_enabled

    def create(
        self,
        plan: Plan,
        *,
        execution_id: str | None = None,
        decision_action: str | None = None,
        require_human: bool = False,
        business_refs: dict[str, Any] | None = None,
    ) -> WorkflowExecution:
        policy = WorkflowRetryPolicy(max_attempts=self.retry_limit)
        wf = workflow_from_plan(
            plan,
            execution_id=execution_id,
            decision_action=decision_action,
            require_human=require_human,
            business_refs=business_refs,
            retry_policy=policy,
        )
        evt = record_workflow_event(
            AUDIT_WORKFLOW_CREATED,
            workflow_id=wf.workflow_id,
            execution_id=execution_id,
            plan_id=plan.plan_id,
            business_refs=business_refs,
        )
        wf.events.append(evt)
        checkpoint_from_workflow(wf)
        return wf

    def run(
        self,
        workflow: WorkflowExecution,
        plan: Plan,
        *,
        goal: str,
        workflow_type: str,
        store_id: str | None = None,
        sku: str | None = None,
        recommendation_id: str | None = None,
        approval_id: str | None = None,
        business_context: dict[str, Any] | None = None,
        actor: str | None = None,
        stop_on_wait: bool = True,
    ) -> WorkflowExecutionResult:
        started = time.perf_counter()
        assert_transition(workflow.status, WorkflowStatus.RUNNING)
        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = workflow.started_at or datetime.now(timezone.utc)
        workflow.events.append(
            record_workflow_event(
                AUDIT_WORKFLOW_STARTED,
                workflow_id=workflow.workflow_id,
                execution_id=workflow.execution_id,
                plan_id=plan.plan_id,
                actor=actor,
            )
        )
        try:
            from eventbus.events import EventType
            from eventbus.publisher import safe_publish

            safe_publish(
                EventType.WORKFLOW_STARTED,
                aggregate_type="workflow",
                aggregate_id=workflow.workflow_id,
                payload={
                    "execution_id": workflow.execution_id,
                    "plan_id": plan.plan_id,
                },
                actor=actor,
                correlation_id=workflow.execution_id,
                metadata={"idempotency_key": f"wf-start:{workflow.workflow_id}"},
            )
        except Exception:  # noqa: BLE001
            pass
        # Emit step-started for ready-ish pending steps (observability).
        for step in plan.steps:
            if step.status in {PlanStepStatus.PENDING, PlanStepStatus.READY}:
                workflow.events.append(
                    record_workflow_event(
                        AUDIT_WORKFLOW_STEP_STARTED,
                        workflow_id=workflow.workflow_id,
                        execution_id=workflow.execution_id,
                        plan_id=plan.plan_id,
                        step_id=step.id,
                        attempt=step.attempt_count + 1,
                        tool=step.tool,
                    )
                )

        try:
            from planner.factory import get_planner
            from planner.service import run_plan_until_blocked

            # Align planner parallel policy with workflow config.
            planner = get_planner()
            if hasattr(planner, "_policy") or True:
                from planner.factory import default_execution_policy

                # Use planner execute with configured parallelism via service.
            plan = run_plan_until_blocked(
                plan,
                goal=goal or workflow.goal,
                workflow=workflow_type or workflow.workflow_type,
                execution_id=workflow.execution_id,
                recommendation_id=recommendation_id,
                approval_id=approval_id,
                store_id=store_id,
                sku=sku,
                business_context=business_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_run_failed err=%s", exc)
            workflow.status = WorkflowStatus.FAILED
            workflow.degraded = True
            workflow.degradation_reason = type(exc).__name__
            workflow.events.append(
                record_workflow_event(
                    AUDIT_WORKFLOW_FAILED,
                    workflow_id=workflow.workflow_id,
                    execution_id=workflow.execution_id,
                    plan_id=plan.plan_id,
                    details={"error": type(exc).__name__},
                )
            )
            checkpoint_from_workflow(workflow)
            return WorkflowExecutionResult(
                workflow=workflow,
                success=False,
                terminal=True,
                failure=WorkflowFailure(
                    failure_class=FailureClass.TECHNICAL_NON_RETRYABLE,
                    error_message=str(exc)[:500],
                ),
                message="Workflow infrastructure failure before/during coordination.",
            )

        workflow = refresh_from_plan(workflow, plan)
        workflow.duration_ms = (time.perf_counter() - started) * 1000.0
        return self._finalize_after_plan(workflow, plan, actor=actor)

    def resume(
        self,
        workflow: WorkflowExecution,
        plan: Plan,
        request: WorkflowResumeRequest,
        *,
        goal: str,
        workflow_type: str,
        store_id: str | None = None,
        sku: str | None = None,
        recommendation_id: str | None = None,
        approval_id: str | None = None,
        business_context: dict[str, Any] | None = None,
    ) -> WorkflowExecutionResult:
        assert_transition(workflow.status, WorkflowStatus.RESUMING)
        workflow.status = WorkflowStatus.RESUMING
        workflow.events.append(
            record_workflow_event(
                AUDIT_WORKFLOW_RESUMED,
                workflow_id=workflow.workflow_id,
                execution_id=workflow.execution_id,
                plan_id=plan.plan_id,
                step_id=request.resolve_step_id,
                actor=request.actor,
                details={"approval_granted": request.approval_granted},
            )
        )
        # Skip completed non-replayable steps — TaskExecutor already no-ops COMPLETED.
        for step in plan.steps:
            if step.status == PlanStepStatus.COMPLETED:
                meta = step.metadata or {}
                if not meta.get("replayable"):
                    continue  # leave completed

        from planner.service import resume_plan_execution

        plan = resume_plan_execution(
            plan,
            goal=goal or workflow.goal,
            workflow=workflow_type or workflow.workflow_type,
            resolve_step_id=request.resolve_step_id,
            execution_id=workflow.execution_id,
            recommendation_id=recommendation_id,
            approval_id=approval_id,
            store_id=store_id,
            sku=sku,
        )
        workflow = refresh_from_plan(workflow, plan)
        return self._finalize_after_plan(workflow, plan, actor=request.actor)

    def cancel(
        self,
        workflow: WorkflowExecution,
        *,
        reason: str = "",
        actor: str | None = None,
        run_compensation: bool = False,
    ) -> WorkflowExecution:
        if str(workflow.status) in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.COMPENSATED,
            WorkflowStatus.CANCELLED,
        }:
            return workflow
        assert_transition(workflow.status, WorkflowStatus.CANCELLED)
        workflow.status = WorkflowStatus.CANCELLED
        for step in workflow.steps:
            if str(step.status) in {
                WorkflowStepStatus.PENDING,
                WorkflowStepStatus.READY,
                WorkflowStepStatus.RETRY_PENDING,
                WorkflowStepStatus.WAITING,
            }:
                step.status = WorkflowStepStatus.CANCELLED
        workflow.events.append(
            record_workflow_event(
                AUDIT_WORKFLOW_CANCELLED,
                workflow_id=workflow.workflow_id,
                execution_id=workflow.execution_id,
                plan_id=workflow.plan_id,
                actor=actor,
                details={"reason": reason, "run_compensation": run_compensation},
            )
        )
        if run_compensation and self.compensation_enabled:
            self._compensate(workflow)
        checkpoint_from_workflow(workflow)
        workflow.completed_at = datetime.now(timezone.utc)
        return workflow

    def _compensate(self, workflow: WorkflowExecution) -> None:
        assert_transition(workflow.status, WorkflowStatus.COMPENSATING)
        workflow.status = WorkflowStatus.COMPENSATING
        workflow.events.append(
            record_workflow_event(
                AUDIT_WORKFLOW_COMPENSATION_STARTED,
                workflow_id=workflow.workflow_id,
                execution_id=workflow.execution_id,
                plan_id=workflow.plan_id,
            )
        )
        for step in reversed(workflow.steps):
            if str(step.status) != WorkflowStepStatus.SUCCEEDED:
                continue
            result = run_compensation_if_configured(
                step, enabled=self.compensation_enabled
            )
            step.compensation = result
            if result.compensatable:
                step.status = WorkflowStepStatus.COMPENSATED
        workflow.status = WorkflowStatus.COMPENSATED
        workflow.events.append(
            record_workflow_event(
                AUDIT_WORKFLOW_COMPENSATION_COMPLETED,
                workflow_id=workflow.workflow_id,
                execution_id=workflow.execution_id,
                plan_id=workflow.plan_id,
            )
        )

    def _finalize_after_plan(
        self,
        workflow: WorkflowExecution,
        plan: Plan,
        *,
        actor: str | None = None,
    ) -> WorkflowExecutionResult:
        # Record per-step completion/failure from plan outputs.
        for step in plan.steps:
            if step.status == PlanStepStatus.COMPLETED:
                workflow.events.append(
                    record_workflow_event(
                        AUDIT_WORKFLOW_STEP_COMPLETED,
                        workflow_id=workflow.workflow_id,
                        execution_id=workflow.execution_id,
                        plan_id=plan.plan_id,
                        step_id=step.id,
                        attempt=step.attempt_count,
                        tool=step.tool,
                    )
                )
            elif step.status == PlanStepStatus.FAILED:
                workflow.events.append(
                    record_workflow_event(
                        AUDIT_WORKFLOW_STEP_FAILED,
                        workflow_id=workflow.workflow_id,
                        execution_id=workflow.execution_id,
                        plan_id=plan.plan_id,
                        step_id=step.id,
                        attempt=step.attempt_count,
                        tool=step.tool,
                        details={"error": step.error},
                    )
                )

        waiting = plan.status == ExecutionState.WAITING or any(
            s.status == PlanStepStatus.WAITING for s in plan.steps
        )
        failed = plan.status == ExecutionState.FAILED or any(
            s.status == PlanStepStatus.FAILED for s in plan.steps
        )
        completed = plan.status == ExecutionState.COMPLETED

        # Retry scheduling for technical failures.
        if failed:
            for step in plan.steps:
                if step.status != PlanStepStatus.FAILED:
                    continue
                from workflow.failures import classify_failure

                fclass, _ = classify_failure(
                    error_code=step.error, message=step.error or ""
                )
                if should_retry(
                    policy=workflow.retry_policy,
                    attempt=step.attempt_count,
                    failure_class=fclass,
                ):
                    delay = next_delay_seconds(workflow.retry_policy, step.attempt_count)
                    workflow.status = WorkflowStatus.RETRY_PENDING
                    if workflow.checkpoint:
                        workflow.checkpoint.retry_state[step.id] = {
                            "attempt": step.attempt_count,
                            "delay_seconds": delay,
                            "failure_class": str(fclass),
                        }
                    workflow.events.append(
                        record_workflow_event(
                            AUDIT_WORKFLOW_RETRY_SCHEDULED,
                            workflow_id=workflow.workflow_id,
                            execution_id=workflow.execution_id,
                            plan_id=plan.plan_id,
                            step_id=step.id,
                            attempt=step.attempt_count,
                            details={"delay_seconds": delay, "failure_class": str(fclass)},
                        )
                    )
                    checkpoint_from_workflow(workflow)
                    return WorkflowExecutionResult(
                        workflow=workflow,
                        success=False,
                        terminal=False,
                        waiting=False,
                        failure=WorkflowFailure(
                            failure_class=fclass,
                            error_message=step.error or "retry pending",
                            retryable=True,
                            step_id=step.id,
                        ),
                        message="Retry scheduled for technical failure.",
                    )
            # Business rejection / non-retryable
            workflow.status = WorkflowStatus.FAILED
            workflow.events.append(
                record_workflow_event(
                    AUDIT_WORKFLOW_FAILED,
                    workflow_id=workflow.workflow_id,
                    execution_id=workflow.execution_id,
                    plan_id=plan.plan_id,
                )
            )
            checkpoint_from_workflow(workflow)
            workflow.completed_at = datetime.now(timezone.utc)
            return WorkflowExecutionResult(
                workflow=workflow,
                success=False,
                terminal=True,
                failure=WorkflowFailure(
                    failure_class=FailureClass.TECHNICAL_NON_RETRYABLE,
                    error_message="Workflow failed without retryable steps.",
                ),
                message="Workflow failed.",
            )

        if waiting:
            workflow.status = WorkflowStatus.WAITING_FOR_HUMAN
            workflow.events.append(
                record_workflow_event(
                    AUDIT_WORKFLOW_WAITING,
                    workflow_id=workflow.workflow_id,
                    execution_id=workflow.execution_id,
                    plan_id=plan.plan_id,
                    details={"reason": "human_or_external_wait"},
                )
            )
            try:
                from eventbus.events import EventType
                from eventbus.publisher import safe_publish

                safe_publish(
                    EventType.WORKFLOW_PAUSED,
                    aggregate_type="workflow",
                    aggregate_id=workflow.workflow_id,
                    payload={"execution_id": workflow.execution_id, "reason": "waiting"},
                    correlation_id=workflow.execution_id,
                    metadata={"idempotency_key": f"wf-pause:{workflow.workflow_id}:{plan.status}"},
                )
                safe_publish(
                    EventType.WORKFLOW_WAITING,
                    aggregate_type="workflow",
                    aggregate_id=workflow.workflow_id,
                    payload={"execution_id": workflow.execution_id},
                    correlation_id=workflow.execution_id,
                    metadata={"idempotency_key": f"wf-wait:{workflow.workflow_id}"},
                )
            except Exception:  # noqa: BLE001
                pass
            checkpoint_from_workflow(workflow)
            return WorkflowExecutionResult(
                workflow=workflow,
                success=False,
                terminal=False,
                waiting=True,
                message="Workflow waiting (HITL/external).",
            )

        if completed:
            has_errors = any(s.status == PlanStepStatus.SKIPPED for s in plan.steps)
            workflow.status = (
                WorkflowStatus.COMPLETED_WITH_ERRORS
                if has_errors
                else WorkflowStatus.COMPLETED
            )
            workflow.completed_at = datetime.now(timezone.utc)
            workflow.events.append(
                record_workflow_event(
                    AUDIT_WORKFLOW_COMPLETED,
                    workflow_id=workflow.workflow_id,
                    execution_id=workflow.execution_id,
                    plan_id=plan.plan_id,
                    actor=actor,
                )
            )
            try:
                from eventbus.events import EventType
                from eventbus.publisher import safe_publish

                safe_publish(
                    EventType.WORKFLOW_COMPLETED,
                    aggregate_type="workflow",
                    aggregate_id=workflow.workflow_id,
                    payload={"execution_id": workflow.execution_id, "plan_id": plan.plan_id},
                    actor=actor,
                    correlation_id=workflow.execution_id,
                    metadata={"idempotency_key": f"wf-done:{workflow.workflow_id}"},
                )
            except Exception:  # noqa: BLE001
                pass
            checkpoint_from_workflow(workflow)
            return WorkflowExecutionResult(
                workflow=workflow,
                success=True,
                terminal=True,
                message="Workflow completed.",
            )

        # Default running/paused
        workflow.status = WorkflowStatus.PAUSED
        checkpoint_from_workflow(workflow)
        return WorkflowExecutionResult(
            workflow=workflow,
            success=False,
            terminal=False,
            message="Workflow paused.",
        )

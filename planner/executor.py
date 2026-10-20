"""Task executor — serial / parallel / fan-in / fan-out with failure policies."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from planner.audit import (
    AUDIT_PLAN_APPROVAL_WAIT,
    AUDIT_PLAN_LLM,
    AUDIT_PLAN_TOOL,
    record_plan_event,
    record_transition,
)
from planner.contracts import (
    ExecutionContext,
    ExecutionPolicy,
    Plan,
    PlanStep,
    StepTransition,
)
from planner.dependencies import DependencyResolver
from planner.types import ExecutionState, FailureAction, PlanStepStatus, PlanStepType

logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    Executes planning steps. Does not implement business math/ERP/approvals.

    Tool steps either mark as delegated or call the LLM tool registry for
    registered read-only knowledge tools — never duplicates agent.tools logic.
    """

    def __init__(
        self,
        *,
        resolver: DependencyResolver | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self._resolver = resolver or DependencyResolver()
        self.policy = policy or ExecutionPolicy()

    def run(
        self,
        plan: Plan,
        context: ExecutionContext,
        *,
        stop_on_wait: bool = True,
        max_cycles: int = 64,
    ) -> Plan:
        plan.status = ExecutionState.RUNNING
        cycles = 0
        while cycles < max_cycles:
            cycles += 1
            ready = self._resolver.ready_steps(plan)
            if not ready:
                if all(
                    s.status
                    in {
                        PlanStepStatus.COMPLETED,
                        PlanStepStatus.SKIPPED,
                        PlanStepStatus.CANCELLED,
                    }
                    for s in plan.steps
                ):
                    plan.status = ExecutionState.COMPLETED
                elif any(s.status == PlanStepStatus.WAITING for s in plan.steps):
                    plan.status = ExecutionState.WAITING
                elif any(s.status == PlanStepStatus.FAILED for s in plan.steps):
                    plan.status = ExecutionState.FAILED
                elif any(s.status == PlanStepStatus.BLOCKED for s in plan.steps):
                    plan.status = ExecutionState.BLOCKED
                else:
                    plan.status = ExecutionState.BLOCKED
                break

            groups = self._resolver.group_parallel(ready)
            if not self.policy.enable_parallel:
                groups = [[s] for g in groups for s in g]

            blocked_wait = False
            for group in groups:
                if len(group) > 1 and self.policy.enable_parallel:
                    self._run_parallel(plan, group, context)
                else:
                    for step in group:
                        self._run_step(plan, step, context)
                        if stop_on_wait and step.status == PlanStepStatus.WAITING:
                            blocked_wait = True
                            break
                        if (
                            self.policy.stop_on_failure
                            and step.status == PlanStepStatus.FAILED
                        ):
                            plan.status = ExecutionState.FAILED
                            plan.updated_at = datetime.now(timezone.utc)
                            return plan
                if blocked_wait:
                    break

            if blocked_wait:
                plan.status = ExecutionState.WAITING
                break

            if any(s.status == PlanStepStatus.FAILED for s in plan.steps) and self.policy.stop_on_failure:
                plan.status = ExecutionState.FAILED
                break

        plan.updated_at = datetime.now(timezone.utc)
        return plan

    def _run_parallel(
        self, plan: Plan, steps: list[PlanStep], context: ExecutionContext
    ) -> None:
        workers = max(1, min(self.policy.max_parallel, len(steps)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._run_step, plan, step, context): step for step in steps
            }
            for fut in as_completed(futures):
                fut.result()

    def _run_step(self, plan: Plan, step: PlanStep, context: ExecutionContext) -> None:
        if step.status == PlanStepStatus.COMPLETED:
            return
        from_status = str(step.status)
        step.status = PlanStepStatus.RUNNING
        step.started_at = datetime.now(timezone.utc)
        step.attempt_count += 1
        started = time.perf_counter()
        record_transition(
            StepTransition(
                plan_id=plan.plan_id,
                step_id=step.id,
                from_status=from_status,
                to_status=str(PlanStepStatus.RUNNING),
                at=step.started_at,
            ),
            execution_id=context.execution_id,
        )

        try:
            output = self._dispatch(plan, step, context)
            step.output = output if isinstance(output, dict) else {"result": output}
            step.status = PlanStepStatus.COMPLETED
            if step.type in {PlanStepType.APPROVAL, PlanStepType.HUMAN, PlanStepType.WAIT}:
                if not step.output.get("resolved"):
                    step.status = PlanStepStatus.WAITING
                    record_plan_event(
                        AUDIT_PLAN_APPROVAL_WAIT,
                        plan_id=plan.plan_id,
                        step_id=step.id,
                        execution_id=context.execution_id,
                        detail={"type": str(step.type)},
                    )
        except Exception as exc:  # noqa: BLE001
            self._handle_failure(plan, step, exc)

        step.duration_ms = (time.perf_counter() - started) * 1000.0
        step.completed_at = datetime.now(timezone.utc)
        record_transition(
            StepTransition(
                plan_id=plan.plan_id,
                step_id=step.id,
                from_status=str(PlanStepStatus.RUNNING),
                to_status=str(step.status),
                duration_ms=step.duration_ms,
                detail=step.error,
                at=step.completed_at,
            ),
            execution_id=context.execution_id,
        )

    def _handle_failure(self, plan: Plan, step: PlanStep, exc: Exception) -> None:
        action = step.retry_policy.on_failure
        step.error = f"{type(exc).__name__}: {exc}"
        step.rollback = {
            "step_id": step.id,
            "attempt": step.attempt_count,
            "action": str(action),
            "error": step.error,
        }
        if (
            action == FailureAction.RETRY
            and step.attempt_count < step.retry_policy.max_attempts
        ):
            step.status = PlanStepStatus.PENDING
            step.error = None
            return
        if action == FailureAction.SKIP:
            step.status = PlanStepStatus.SKIPPED
            return
        if action == FailureAction.MANUAL:
            step.status = PlanStepStatus.WAITING
            step.metadata["manual_intervention"] = True
            return
        step.status = PlanStepStatus.FAILED

    def _dispatch(
        self, plan: Plan, step: PlanStep, context: ExecutionContext
    ) -> dict[str, Any]:
        if step.type == PlanStepType.FINISH:
            return {"finished": True}
        if step.type == PlanStepType.DECISION:
            return self._run_decision(plan, step, context)
        if step.type == PlanStepType.ACTION:
            if step.id.startswith("load_memory") or step.expected_output == "memory_context":
                return self._load_memory(context)
            return {"action": step.name, "resolved": True}
        if step.type in {PlanStepType.APPROVAL, PlanStepType.HUMAN, PlanStepType.WAIT}:
            # Pause for HITL — business approval services unchanged.
            resume_token = context.variables.get("resume_resolved")
            if resume_token or context.variables.get(f"resolve:{step.id}"):
                return {"resolved": True, "resumed": True}
            return {"resolved": False, "waiting": True}
        if step.type == PlanStepType.LLM:
            return self._run_llm(plan, step, context)
        if step.type == PlanStepType.TOOL:
            return self._run_tool(plan, step, context)
        return {"noop": True}

    def _load_memory(self, context: ExecutionContext) -> dict[str, Any]:
        try:
            from memory.service import assemble_execution_context

            assembled = assemble_execution_context(
                recommendation_id=context.recommendation_id,
                approval_id=context.approval_id,
                purchase_order_id=context.purchase_order_id,
                supplier_id=context.supplier_id,
                store_id=context.store_id,
                sku=context.sku,
                execution_id=context.execution_id,
            )
            context.memory_context = assembled.llm_context
            return {
                "memory_retrieved": assembled.record_count > 0,
                "record_count": assembled.record_count,
                "resolved": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("planner_memory_failed err=%s", exc)
            return {"memory_retrieved": False, "resolved": True, "error": str(exc)}

    def _run_decision(
        self, plan: Plan, step: PlanStep, context: ExecutionContext
    ) -> dict[str, Any]:
        """Decision Intelligence evaluation — advisory; does not execute business actions."""
        try:
            from decision.service import evaluate_decision

            memory_payload = {}
            if isinstance(context.variables.get("memory"), dict):
                memory_payload = context.variables["memory"]
            outcome = evaluate_decision(
                execution_id=context.execution_id,
                goal=context.goal or plan.goal,
                workflow=context.workflow or plan.workflow,
                store_id=context.store_id,
                sku=context.sku,
                supplier_id=context.supplier_id,
                recommendation_id=context.recommendation_id,
                approval_id=context.approval_id,
                actor_role=context.actor_role,
                business_context=dict(context.business_context or {}),
                memory=memory_payload,
                policy=(context.business_context or {}).get("policy")
                or (context.business_context or {}).get("policy_evaluation"),
            )
            ops = outcome.to_ops_summary()
            context.variables["decision_ops"] = ops
            context.business_context["decision_recommendation"] = {
                "action": str(outcome.recommendation.action),
                "require_human": outcome.recommendation.require_human,
                "evaluation_id": outcome.evaluation_id,
            }
            return {
                "resolved": True,
                "decision": str(outcome.recommendation.action),
                "require_human": outcome.recommendation.require_human,
                "decision_ops": ops,
            }
        except Exception as exc:  # noqa: BLE001
            # Fail-soft: planner continues with default business path.
            return {
                "resolved": True,
                "decision": "continue",
                "degraded": True,
                "error": type(exc).__name__,
                "decision_ops": {
                    "degraded": True,
                    "degradation_reason": type(exc).__name__,
                    "require_human": True,
                },
            }

    def _run_llm(
        self, plan: Plan, step: PlanStep, context: ExecutionContext
    ) -> dict[str, Any]:
        from llm.service import prepare_runtime_llm_call

        started = time.perf_counter()
        result = prepare_runtime_llm_call(
            workflow=context.workflow or plan.workflow,
            user_input=context.goal or plan.goal,
            execution_id=context.execution_id,
            recommendation_id=context.recommendation_id,
            approval_id=context.approval_id,
            store_id=context.store_id,
            sku=context.sku,
            business_context=context.business_context,
            invoke=True,
            allowed_tools=[],
            response_schema={"required": ["status"]},
        )
        duration = (time.perf_counter() - started) * 1000.0
        record_plan_event(
            AUDIT_PLAN_LLM,
            plan_id=plan.plan_id,
            step_id=step.id,
            duration_ms=duration,
            execution_id=context.execution_id,
            detail={"provider": result.get("provider"), "model": result.get("model")},
        )
        return {
            "resolved": True,
            "llm_ops": result.get("llm_ops"),
            "structured": result.get("structured"),
        }

    def _run_tool(
        self, plan: Plan, step: PlanStep, context: ExecutionContext
    ) -> dict[str, Any]:
        tool = step.tool or ""
        started = time.perf_counter()
        # Mutating / business tools are marked delegated — Agent Runtime / services own them.
        mutating = {
            "create_recommendation_record",
            "create_approval_request",
            "create_mock_purchase_order",
        }
        if tool in mutating or step.metadata.get("delegated"):
            record_plan_event(
                AUDIT_PLAN_TOOL,
                plan_id=plan.plan_id,
                step_id=step.id,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                execution_id=context.execution_id,
                detail={"tool": tool, "delegated": True},
            )
            return {"resolved": True, "delegated": True, "tool": tool}

        try:
            from llm.tools.registry import execute_registered_tool

            out = execute_registered_tool(
                tool,
                {
                    "store_id": context.store_id,
                    "sku": context.sku,
                    "recommendation_id": context.recommendation_id,
                    "approval_id": context.approval_id,
                    "execution_id": context.execution_id,
                },
            )
            record_plan_event(
                AUDIT_PLAN_TOOL,
                plan_id=plan.plan_id,
                step_id=step.id,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                execution_id=context.execution_id,
                detail={"tool": tool, "delegated": False},
            )
            return {"resolved": True, "tool": tool, "result": out}
        except Exception:
            # Unregistered for direct execution — still mark as delegated for runtime.
            record_plan_event(
                AUDIT_PLAN_TOOL,
                plan_id=plan.plan_id,
                step_id=step.id,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                execution_id=context.execution_id,
                detail={"tool": tool, "delegated": True},
            )
            return {"resolved": True, "delegated": True, "tool": tool}

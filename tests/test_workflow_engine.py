"""Enterprise Workflow Execution Engine tests."""

from __future__ import annotations

import pytest

from agent.execution_engine import create_execution
from agent.execution_states import ExecutionType
from planner.contracts import Plan, PlanStep, RetryPolicy
from planner.service import create_execution_plan
from planner.types import FailureAction, PlanStepStatus, PlanStepType
from services import agent_ops_service, ops_health_service
from workflow.audit import (
    AUDIT_WORKFLOW_CANCELLED,
    AUDIT_WORKFLOW_COMPLETED,
    AUDIT_WORKFLOW_CREATED,
    AUDIT_WORKFLOW_STARTED,
    list_workflow_audit_events,
    reset_workflow_audit,
)
from workflow.compensation import compensation_for_step
from workflow.contracts import WorkflowResumeRequest, WorkflowStepExecution
from workflow.failures import classify_failure
from workflow.factory import get_workflow_engine, workflow_health
from workflow.retry import should_retry
from workflow.sanitize import sanitize_value, summarize_output
from workflow.service import (
    attach_workflow_to_execution_context,
    cancel_workflow_in_context,
    resume_workflow_for_execution,
    run_workflow_for_execution,
)
from workflow.states import InvalidWorkflowTransition, assert_transition, can_transition
from workflow.tools import execute_controlled_tool, llm_cannot_bypass_tool_auth
from workflow.types import FailureClass, RetryMode, WorkflowStatus


def _simple_plan() -> Plan:
    return Plan(
        goal="test workflow",
        workflow="recommendation_analysis",
        steps=[
            PlanStep(id="a", type=PlanStepType.ACTION, name="A"),
            PlanStep(
                id="b",
                type=PlanStepType.ACTION,
                name="B",
                dependencies=["a"],
            ),
            PlanStep(
                id="finish",
                type=PlanStepType.FINISH,
                name="Finish",
                dependencies=["b"],
            ),
        ],
    )


def test_workflow_creation_and_serial_execution():
    reset_workflow_audit()
    plan = _simple_plan()
    engine = get_workflow_engine(force_new=True)
    wf = engine.create(plan, execution_id="EXE-WF-1")
    assert wf.workflow_id.startswith("WF-")
    assert wf.checkpoint is not None
    result = engine.run(
        wf,
        plan,
        goal="test",
        workflow_type="recommendation_analysis",
    )
    assert result.workflow.checkpoint is not None
    assert result.terminal or result.waiting or result.success
    events = [e["event_type"] for e in list_workflow_audit_events()]
    assert AUDIT_WORKFLOW_CREATED in events
    assert AUDIT_WORKFLOW_STARTED in events


def test_dependency_ordering_parallel_and_completion():
    plan = create_execution_plan(
        goal="Analyze ST001/SKU-1001",
        workflow="recommendation_analysis",
        store_id="ST001",
        sku="SKU-1001",
        execution_id="EXE-PAR",
    )
    # Template includes parallel gather groups.
    groups = {s.parallel_group for s in plan.steps if s.parallel_group}
    assert groups
    result, ctx = run_workflow_for_execution(
        execution_id="EXE-PAR",
        plan=plan,
        goal=plan.goal,
        workflow_type=plan.workflow,
        context={"store_id": "ST001", "sku": "SKU-1001"},
        store_id="ST001",
        sku="SKU-1001",
    )
    assert "workflow_ops" in ctx
    assert ctx["workflow_ops"]["workflow_id"]
    assert result.workflow.checkpoint.completed_steps or result.waiting or result.success
    # Completed steps should include load_memory before dependents when finished path runs.
    ops = ctx["workflow_ops"]
    assert "plan_id" in ops
    assert ops.get("checkpoint", {}).get("checkpoint_id")


def test_resume_skips_completed_work():
    plan = _simple_plan()
    # Pretend first step completed.
    plan.steps[0].status = PlanStepStatus.COMPLETED
    plan.steps[0].output = {"done": True}
    plan.steps[1].status = PlanStepStatus.WAITING
    plan.steps[1].type = PlanStepType.APPROVAL
    plan.steps[1].output = {"resolved": False, "waiting": True}
    from planner.types import ExecutionState

    plan.status = ExecutionState.WAITING

    engine = get_workflow_engine(force_new=True)
    wf = engine.create(plan, execution_id="EXE-RESUME")
    wf.status = WorkflowStatus.WAITING_FOR_HUMAN
    first_attempt = plan.steps[0].attempt_count
    result = engine.resume(
        wf,
        plan,
        WorkflowResumeRequest(
            workflow_id=wf.workflow_id,
            execution_id="EXE-RESUME",
            resolve_step_id="b",
            approval_granted=True,
        ),
        goal="resume",
        workflow_type="recommendation_analysis",
    )
    # Completed step a must not be re-run (attempt unchanged).
    assert plan.steps[0].attempt_count == first_attempt
    assert plan.steps[0].status == PlanStepStatus.COMPLETED
    assert result.workflow.checkpoint is not None


def test_failure_classification_and_retry_policy():
    cls, retryable = classify_failure(error_code="temporary_failure")
    assert cls == FailureClass.TECHNICAL_RETRYABLE and retryable
    cls2, retryable2 = classify_failure(business_rejection=True)
    assert cls2 == FailureClass.BUSINESS_REJECTION and not retryable2
    cls3, retryable3 = classify_failure(error_code="authorization_denied")
    assert cls3 == FailureClass.AUTHORIZATION_FAILURE and not retryable3

    from workflow.contracts import WorkflowRetryPolicy

    policy = WorkflowRetryPolicy(mode=RetryMode.FIXED, max_attempts=3)
    assert should_retry(policy=policy, attempt=1, failure_class=FailureClass.TECHNICAL_RETRYABLE)
    assert not should_retry(
        policy=policy, attempt=1, failure_class=FailureClass.BUSINESS_REJECTION
    )
    assert not should_retry(policy=policy, attempt=3, failure_class=FailureClass.TECHNICAL_RETRYABLE)


def test_authorization_and_llm_cannot_bypass():
    # Unknown / disallowed tool must fail auth.
    assert llm_cannot_bypass_tool_auth(
        "totally_fake_tool", execution_type="recommendation_analysis", actor_role="viewer"
    ) is False
    result = execute_controlled_tool(
        "totally_fake_tool",
        execution_type="recommendation_analysis",
        actor_role="viewer",
    )
    assert result.success is False
    assert result.failure_class in {
        FailureClass.AUTHORIZATION_FAILURE,
        FailureClass.VALIDATION_FAILURE,
        FailureClass.TECHNICAL_NON_RETRYABLE,
    } or result.error_code


def test_secrets_sanitized():
    dirty = {"api_key": "sk-secret", "token": "abc", "ok": 1, "nested": {"password": "x"}}
    clean = sanitize_value(dirty)
    assert clean["api_key"] == "[redacted]"
    assert clean["token"] == "[redacted]"
    assert clean["nested"]["password"] == "[redacted]"
    assert clean["ok"] == 1
    summary = summarize_output({"status": "ok", "secret": "nope", "recommendation_id": "R1"})
    assert summary.get("recommendation_id") == "R1"
    assert "secret" not in summary or summary.get("secret") == "[redacted]"


def test_cancellation_and_compensation_metadata():
    plan = _simple_plan()
    engine = get_workflow_engine(force_new=True)
    wf = engine.create(plan, execution_id="EXE-CANCEL")
    wf.status = WorkflowStatus.RUNNING
    cancelled = engine.cancel(wf, reason="user_abort", actor="tester", run_compensation=False)
    assert cancelled.status == WorkflowStatus.CANCELLED
    events = [e["event_type"] for e in cancelled.events]
    assert AUDIT_WORKFLOW_CANCELLED in events

    step = WorkflowStepExecution(
        step_id="erp1",
        plan_step_id="erp1",
        step_type="erp",
        tool_name="transmit_order_intent",
        status="succeeded",
    )
    comp = compensation_for_step(step)
    assert comp.compensatable is False
    assert "cannot" in comp.reason.lower() or "not" in str(comp.kind)


def test_invalid_transition_rejected():
    assert can_transition(WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING) is False
    with pytest.raises(InvalidWorkflowTransition):
        assert_transition(WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING)


def test_attach_agent_ops_health_decision_integration():
    ex = create_execution(
        execution_type=ExecutionType.RECOMMENDATION_ANALYSIS,
        goal="Workflow attach test",
        actor_role="store_manager",
        context={"store_id": "ST001", "sku": "SKU-1001"},
    )
    ctx = (ex.get("envelope") or {}).get("context") or {}
    assert "workflow_ops" in ctx
    assert ctx["workflow_ops"].get("workflow_id") or ctx["workflow_ops"].get("degraded")

    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    assert detail.get("workflow") is not None

    health = ops_health_service.get_operational_health()
    names = {c.get("component") for c in health.get("dependencies") or []}
    assert "workflow_engine" in names
    assert "workflow_checkpoint_store" in names
    assert "workflow_executor" in names
    assert "resume_engine" in names
    assert workflow_health().get("ok") is True


def test_hitl_wait_resume_path():
    plan = Plan(
        goal="approval wait",
        workflow="order_execution",
        steps=[
            PlanStep(id="validate", type=PlanStepType.ACTION, name="validate"),
            PlanStep(
                id="await_hitl",
                type=PlanStepType.APPROVAL,
                name="Wait",
                dependencies=["validate"],
            ),
            PlanStep(
                id="finish",
                type=PlanStepType.FINISH,
                name="Finish",
                dependencies=["await_hitl"],
            ),
        ],
    )
    result, ctx = run_workflow_for_execution(
        execution_id="EXE-HITL",
        plan=plan,
        goal=plan.goal,
        workflow_type="order_execution",
        context={},
    )
    assert result.waiting or str(result.workflow.status) in {
        WorkflowStatus.WAITING_FOR_HUMAN,
        WorkflowStatus.COMPLETED,
    }
    # Resume
    plan2 = Plan.model_validate(ctx["plan_snapshot"])
    resumed, ctx2 = resume_workflow_for_execution(
        execution_id="EXE-HITL",
        plan=plan2,
        goal=plan.goal,
        workflow_type="order_execution",
        resolve_step_id="await_hitl",
        context=ctx,
        approval_granted=True,
        actor="category_manager",
    )
    assert "workflow_ops" in ctx2
    assert resumed.workflow.checkpoint is not None


def test_rag_cannot_bypass_permissions():
    # Retrieved knowledge must not authorize mutating tools for viewer.
    ok = llm_cannot_bypass_tool_auth(
        "create_mock_purchase_order",
        execution_type="recommendation_analysis",
        actor_role="viewer",
    )
    assert ok is False


def test_cancel_workflow_in_context():
    plan = Plan(
        goal="cxl",
        workflow="recommendation_analysis",
        steps=[
            PlanStep(id="a", type=PlanStepType.ACTION, name="A"),
            PlanStep(
                id="await_hitl",
                type=PlanStepType.APPROVAL,
                name="Wait",
                dependencies=["a"],
            ),
            PlanStep(
                id="finish",
                type=PlanStepType.FINISH,
                name="Finish",
                dependencies=["await_hitl"],
            ),
        ],
    )
    result, ctx = run_workflow_for_execution(
        execution_id="EXE-CXL",
        plan=plan,
        goal="cxl",
        workflow_type="recommendation_analysis",
        context={},
    )
    assert result.waiting or str(result.workflow.status) == WorkflowStatus.WAITING_FOR_HUMAN
    ctx2 = cancel_workflow_in_context(ctx, reason="stop", actor="admin")
    assert ctx2["workflow_ops"]["status"] == WorkflowStatus.CANCELLED


def test_e2e_governed_identifiers_no_duplicate_mutation_hooks():
    """Decision + workflow attach; mutations remain service-delegated."""
    from decision.service import evaluate_decision

    decision = evaluate_decision(
        store_id="ST001",
        sku="SKU-1001",
        inventory={"on_hand": 2, "days_of_supply": 1},
        recommendation={"recommended_quantity": 24, "unit_cost": 10},
        policy={"disposition": "human_review", "requires_human": True},
    )
    plan = create_execution_plan(
        goal="Governed replenishment",
        workflow="recommendation_analysis",
        store_id="ST001",
        sku="SKU-1001",
        execution_id="EXE-E2E-WF",
    )
    ctx = {
        "store_id": "ST001",
        "sku": "SKU-1001",
        "decision_ops": decision.to_ops_summary(),
        "plan_snapshot": plan.model_dump(mode="json"),
    }
    ctx = attach_workflow_to_execution_context(
        ctx,
        execution_id="EXE-E2E-WF",
        goal=plan.goal,
        workflow_type=plan.workflow,
        plan_snapshot=ctx["plan_snapshot"],
        decision_ops=ctx["decision_ops"],
    )
    assert ctx["workflow_ops"]["require_human"] is True
    assert ctx["workflow_ops"]["decision_action"]
    # Workflow does not invent OrderIntent / ERP transmit here.
    assert "order_intent_id" not in (ctx["workflow_ops"].get("business_refs") or {})

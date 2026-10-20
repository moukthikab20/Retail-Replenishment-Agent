"""Enterprise Planning & Task Graph Engine tests."""

from __future__ import annotations

import pytest

from agent.execution_engine import create_execution
from agent.execution_states import ExecutionType
from integrations.failures import ProviderConfigError
from planner.audit import list_plan_audits, reset_plan_audit
from planner.contracts import (
    ExecutionContext,
    ExecutionPolicy,
    Plan,
    PlanStep,
    RetryPolicy,
)
from planner.dependencies import DependencyResolver
from planner.executor import TaskExecutor
from planner.factory import (
    get_planner,
    reset_planner,
    validate_planner_provider_configuration,
)
from planner.service import (
    attach_plan_to_execution_context,
    create_execution_plan,
    resume_plan_execution,
    run_plan_until_blocked,
)
from planner.types import (
    ExecutionState,
    FailureAction,
    PlanStepStatus,
    PlanStepType,
)
from planner.validator import PlanValidator
from services import agent_ops_service


def test_unknown_planner_provider_fails_fast(monkeypatch):
    monkeypatch.setattr("config.PLANNER_PROVIDER", "autogen")
    monkeypatch.setattr("planner.factory.PLANNER_PROVIDER", "autogen")
    reset_planner()
    with pytest.raises(ProviderConfigError):
        validate_planner_provider_configuration()
    with pytest.raises(ProviderConfigError):
        get_planner(force_new=True)


def test_plan_creation_and_validation():
    reset_planner()
    plan = create_execution_plan(
        goal="Analyze ST001/SKU-1001",
        workflow="recommendation_analysis",
        store_id="ST001",
        sku="SKU-1001",
        execution_id="EXE-PLAN-1",
    )
    assert plan.plan_id
    assert plan.steps
    assert any(s.type == PlanStepType.FINISH for s in plan.steps)
    assert any(s.type == PlanStepType.LLM for s in plan.steps)
    errors = PlanValidator().validate(plan)
    assert errors == []
    audits = list_plan_audits(plan_id=plan.plan_id)
    assert any(a["event_type"] == "plan_created" for a in audits)


def test_dependency_resolution_and_ordering():
    resolver = DependencyResolver()
    plan = Plan(
        goal="test",
        steps=[
            PlanStep(id="a", type=PlanStepType.ACTION, name="a"),
            PlanStep(
                id="b",
                type=PlanStepType.ACTION,
                name="b",
                dependencies=["a"],
                parallel_group="g1",
            ),
            PlanStep(
                id="c",
                type=PlanStepType.ACTION,
                name="c",
                dependencies=["a"],
                parallel_group="g1",
            ),
            PlanStep(
                id="d",
                type=PlanStepType.FINISH,
                name="d",
                dependencies=["b", "c"],
            ),
        ],
    )
    assert resolver.validate_acyclic(plan) == []
    order = resolver.topological_order(plan)
    assert order.index("a") < order.index("b")
    assert order.index("a") < order.index("c")
    assert order.index("d") > order.index("b")
    ready = resolver.ready_steps(plan)
    assert [s.id for s in ready] == ["a"]
    plan.steps[0].status = PlanStepStatus.COMPLETED
    ready2 = resolver.ready_steps(plan)
    assert {s.id for s in ready2} == {"b", "c"}
    groups = resolver.group_parallel(ready2)
    assert any(len(g) == 2 for g in groups)


def test_parallel_execution():
    reset_planner()
    plan = create_execution_plan(
        goal="scenario",
        workflow="scenario_analysis",
        recommendation_id="REC-1",
        execution_id="EXE-PAR",
    )
    # Ensure parallel group present
    assert any(s.parallel_group for s in plan.steps)
    executed = run_plan_until_blocked(
        plan,
        goal="scenario",
        workflow="scenario_analysis",
        execution_id="EXE-PAR",
        recommendation_id="REC-1",
    )
    assert executed.status in {
        ExecutionState.COMPLETED,
        ExecutionState.WAITING,
        ExecutionState.RUNNING,
        ExecutionState.FAILED,
    }
    # Parallel scenario tools should complete (delegated)
    statuses = {s.id: s.status for s in executed.steps}
    assert statuses.get("evaluate_quantity") in {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.SKIPPED,
    }
    assert statuses.get("evaluate_delay") in {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.SKIPPED,
    }


def test_execution_ordering_serial_chain():
    policy = ExecutionPolicy(enable_parallel=False, max_parallel=1)
    executor = TaskExecutor(policy=policy)
    plan = Plan(
        goal="serial",
        steps=[
            PlanStep(id="s1", type=PlanStepType.DECISION, name="one"),
            PlanStep(
                id="s2",
                type=PlanStepType.DECISION,
                name="two",
                dependencies=["s1"],
            ),
            PlanStep(
                id="s3",
                type=PlanStepType.FINISH,
                name="done",
                dependencies=["s2"],
            ),
        ],
    )
    ctx = ExecutionContext(goal="serial", workflow="generic", execution_id="EXE-SER")
    out = executor.run(plan, ctx)
    assert out.status == ExecutionState.COMPLETED
    assert [s.status for s in out.steps] == [
        PlanStepStatus.COMPLETED,
        PlanStepStatus.COMPLETED,
        PlanStepStatus.COMPLETED,
    ]
    assert out.steps[0].completed_at <= out.steps[1].completed_at


def test_approval_wait_and_resume():
    reset_plan_audit()
    reset_planner()
    plan = create_execution_plan(
        goal="Create order",
        workflow="order_execution",
        approval_id="APR-1",
        execution_id="EXE-ORD",
    )
    blocked = run_plan_until_blocked(
        plan,
        goal="Create order",
        workflow="order_execution",
        approval_id="APR-1",
        execution_id="EXE-ORD",
    )
    assert blocked.status == ExecutionState.WAITING
    wait_step = next(s for s in blocked.steps if s.id == "await_hitl")
    assert wait_step.status == PlanStepStatus.WAITING
    audits = list_plan_audits(plan_id=blocked.plan_id)
    assert any(a["event_type"] == "plan_approval_wait" for a in audits)

    resumed = resume_plan_execution(
        blocked,
        goal="Create order",
        workflow="order_execution",
        resolve_step_id="await_hitl",
        execution_id="EXE-ORD",
        approval_id="APR-1",
    )
    assert resumed.step_map()["await_hitl"].status == PlanStepStatus.COMPLETED
    assert resumed.status in {ExecutionState.COMPLETED, ExecutionState.WAITING}
    assert any(a["event_type"] == "plan_resumed" for a in list_plan_audits(plan_id=resumed.plan_id))


def test_retry_and_step_failure():
    policy = ExecutionPolicy(stop_on_failure=True)

    class FailingExecutor(TaskExecutor):
        def _dispatch(self, plan, step, context):
            raise RuntimeError("forced")

    executor = FailingExecutor(policy=policy)
    plan = Plan(
        goal="fail",
        steps=[
            PlanStep(
                id="bad",
                type=PlanStepType.ACTION,
                name="bad",
                retry_policy=RetryPolicy(
                    max_attempts=2, on_failure=FailureAction.RETRY
                ),
            ),
            PlanStep(
                id="finish",
                type=PlanStepType.FINISH,
                name="finish",
                dependencies=["bad"],
            ),
        ],
    )
    ctx = ExecutionContext(goal="fail", workflow="generic")
    out = executor.run(plan, ctx, max_cycles=10)
    assert out.step_map()["bad"].status == PlanStepStatus.FAILED
    assert out.step_map()["bad"].attempt_count >= 2
    assert out.step_map()["bad"].rollback
    assert out.status == ExecutionState.FAILED


def test_skip_on_failure_policy():
    class SkippingExecutor(TaskExecutor):
        def _dispatch(self, plan, step, context):
            if step.type == PlanStepType.FINISH:
                return {"finished": True}
            raise RuntimeError("x")

    executor = SkippingExecutor(policy=ExecutionPolicy(stop_on_failure=False))
    plan = Plan(
        goal="skip",
        steps=[
            PlanStep(
                id="skipme",
                type=PlanStepType.ACTION,
                retry_policy=RetryPolicy(max_attempts=1, on_failure=FailureAction.SKIP),
            ),
            PlanStep(
                id="finish",
                type=PlanStepType.FINISH,
                dependencies=["skipme"],
            ),
        ],
    )
    out = executor.run(plan, ExecutionContext(goal="skip", workflow="generic"))
    assert out.step_map()["skipme"].status == PlanStepStatus.SKIPPED
    assert out.step_map()["finish"].status == PlanStepStatus.COMPLETED
    assert out.status == ExecutionState.COMPLETED


def test_plan_validation_rejects_cycles_and_bad_tools():
    validator = PlanValidator()
    cyclic = Plan(
        goal="cycle",
        steps=[
            PlanStep(id="a", type=PlanStepType.ACTION, dependencies=["b"]),
            PlanStep(id="b", type=PlanStepType.FINISH, dependencies=["a"]),
        ],
    )
    errors = validator.validate(cyclic)
    assert "cycle_detected" in errors

    empty = Plan(goal="", steps=[])
    errors2 = validator.validate(empty)
    assert "empty_plan" in errors2
    assert "missing_goal" in errors2


def test_attach_plan_and_agent_ops(monkeypatch):
    monkeypatch.setattr("config.PLANNER_PROVIDER", "mock")
    monkeypatch.setattr("planner.factory.PLANNER_PROVIDER", "mock")
    reset_planner()
    ctx, plan = attach_plan_to_execution_context(
        {"store_id": "ST001", "sku": "SKU-1001"},
        goal="ops plan",
        workflow="recommendation_analysis",
        execution_id="EXE-ATT-PLAN",
        store_id="ST001",
        sku="SKU-1001",
    )
    assert plan is not None
    assert "plan_ops" in ctx
    assert ctx["plan_ops"]["plan_id"] == plan.plan_id
    assert "resume_state" in ctx["plan_ops"]

    ex = create_execution(
        execution_type=ExecutionType.RECOMMENDATION_ANALYSIS,
        goal="planning visibility",
        context={"store_id": "ST001", "sku": "SKU-1001"},
    )
    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    planning = detail.get("planning")
    assert isinstance(planning, dict)
    assert planning.get("plan_id")
    assert "current_step" in planning
    assert "completed_steps" in planning
    assert "blocked_steps" in planning
    assert "parallel_branches" in planning
    assert "resume_state" in planning
    assert "timeline" in planning


def test_rules_provider_selection(monkeypatch):
    monkeypatch.setattr("config.PLANNER_PROVIDER", "rules")
    monkeypatch.setattr("planner.factory.PLANNER_PROVIDER", "rules")
    reset_planner()
    planner = get_planner(force_new=True)
    assert planner.provider_name == "rules"
    plan = planner.create_plan(
        ExecutionContext(goal="x", workflow="follow_up", execution_id="EXE-R")
    )
    assert plan.provider == "rules"

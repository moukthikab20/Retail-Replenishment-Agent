"""Planning engine enums."""

from __future__ import annotations

from enum import StrEnum


class PlanStepType(StrEnum):
    ACTION = "action"
    DECISION = "decision"
    APPROVAL = "approval"
    TOOL = "tool"
    LLM = "llm"
    HUMAN = "human"
    WAIT = "wait"
    FINISH = "finish"


class PlanStepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class FailureAction(StrEnum):
    RETRY = "retry"
    FAIL = "fail"
    SKIP = "skip"
    MANUAL = "manual_intervention"


class ExecutionState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

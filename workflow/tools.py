"""Controlled tool execution — authorization + typed ToolExecutionResult."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from workflow.contracts import ToolExecutionResult
from workflow.failures import classify_failure
from workflow.sanitize import extract_business_refs, summarize_output
from workflow.types import FailureClass


def execute_controlled_tool(
    tool_name: str,
    *,
    arguments: dict[str, Any] | None = None,
    execution_type: str | None = None,
    actor_role: str | None = None,
    attempt: int = 1,
    invoke: bool = True,
) -> ToolExecutionResult:
    """
    Validate registry + auth, then optionally invoke registered tool.
    Mutating tools remain delegated to business services — this wrapper
    never reimplements their logic.
    """
    call_id = f"tc-{uuid4().hex[:10]}"
    started = datetime.now(timezone.utc)
    try:
        from agent.tool_registry import (
            assert_tool_allowed_for_execution,
            get_tool_definition,
        )

        meta = assert_tool_allowed_for_execution(
            tool_name, execution_type=execution_type, actor_role=actor_role
        )
        if meta.requires_authorization and meta.read_only is False:
            # Mutating path: do not invent business mutation here.
            if not invoke:
                return ToolExecutionResult(
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    status="authorized_deferred",
                    success=True,
                    retryable=False,
                    attempt=attempt,
                    started_at=started,
                    completed_at=datetime.now(timezone.utc),
                    output_summary={"delegated": True, "mutating": True},
                )
            # Prefer existing registry execute for read tools; mutating stay delegated.
            if not meta.read_only:
                completed = datetime.now(timezone.utc)
                return ToolExecutionResult(
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    status="delegated",
                    success=True,
                    retryable=bool(meta.retryable),
                    attempt=attempt,
                    started_at=started,
                    completed_at=completed,
                    duration_ms=(completed - started).total_seconds() * 1000.0,
                    output_summary={
                        "delegated": True,
                        "message": "Mutating tool must run via authoritative business service.",
                    },
                )

        from llm.tools.registry import execute_registered_tool

        raw = execute_registered_tool(tool_name, dict(arguments or {}))
        completed = datetime.now(timezone.utc)
        summary = summarize_output(raw if isinstance(raw, dict) else {"result": raw})
        return ToolExecutionResult(
            tool_name=tool_name,
            tool_call_id=call_id,
            status="succeeded",
            success=True,
            retryable=bool(meta.retryable),
            attempt=attempt,
            started_at=started,
            completed_at=completed,
            duration_ms=(completed - started).total_seconds() * 1000.0,
            output_summary=summary,
            business_refs=extract_business_refs(summary),
        )
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", None) or type(exc).__name__
        failure_class, retryable = classify_failure(
            error=exc, error_code=str(code), message=str(exc)
        )
        completed = datetime.now(timezone.utc)
        return ToolExecutionResult(
            tool_name=tool_name,
            tool_call_id=call_id,
            status="failed",
            success=False,
            retryable=retryable,
            attempt=attempt,
            started_at=started,
            completed_at=completed,
            duration_ms=(completed - started).total_seconds() * 1000.0,
            error_code=str(code),
            error_message=str(exc)[:500],
            failure_class=failure_class,
        )


def llm_cannot_bypass_tool_auth(
    tool_name: str, *, execution_type: str | None, actor_role: str | None
) -> bool:
    """Return True if server-side auth would allow; raises/False on bypass attempt."""
    try:
        from agent.tool_registry import assert_tool_allowed_for_execution

        assert_tool_allowed_for_execution(
            tool_name, execution_type=execution_type, actor_role=actor_role
        )
        return True
    except Exception:
        return False

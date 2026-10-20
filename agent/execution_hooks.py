"""SDK RunHooks that journal tool/model lifecycle into the durable execution engine."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agents import Agent, RunHooks
from agents.items import ModelResponse
from agents.run_context import AgentHookContext, RunContextWrapper
from agents.tool import Tool

try:
    from agents.tool_context import ToolContext as _ToolContext
except ImportError:  # pragma: no cover - older SDKs
    _ToolContext = None  # type: ignore[misc, assignment]

from agent.context import ReplenishmentRunContext
from agent.execution_engine import (
    record_model_turn_end,
    record_model_turn_start,
    record_tool_finish,
    record_tool_start,
)
from agent.execution_failures import classify_failure
from agent.execution_envelope import new_tool_call_id
from agent.tool_registry import assert_tool_allowed_for_execution, get_tool_definition

logger = logging.getLogger(__name__)

_SENSITIVE = frozenset(
    {"api_key", "openai_api_key", "authorization", "password", "secret", "token", "access_code"}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE or "api_key" in str(key).lower():
                out[key] = "[redacted]"
            else:
                out[key] = _sanitize(item)
        return out
    if isinstance(value, list):
        return [_sanitize(v) for v in value[:50]]
    if isinstance(value, str) and len(value) > 1500:
        return value[:1500] + "…"
    return value


def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"raw": raw[:500]}
        except json.JSONDecodeError:
            return {"raw": raw[:500]}
    return {"value": str(raw)[:500]}


def _summarize_output(result: object) -> dict[str, Any]:
    if result is None:
        return {"result": None}
    if isinstance(result, dict):
        summary: dict[str, Any] = {"keys": list(result.keys())[:40]}
        for key in (
            "recommendation_id",
            "approval_id",
            "purchase_order_id",
            "status",
            "disposition",
            "store_id",
            "sku",
        ):
            if key in result:
                summary[key] = result[key]
        return _sanitize(summary)
    text = str(result)
    return {"type": type(result).__name__, "preview": text[:400]}


def _usage_from_response(response: ModelResponse) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {
        "input_tokens": getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None)
        or getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _ctx(wrapper: RunContextWrapper[Any] | AgentHookContext[Any] | None) -> ReplenishmentRunContext | None:
    if wrapper is None:
        return None
    ctx = getattr(wrapper, "context", None)
    if isinstance(ctx, ReplenishmentRunContext):
        return ctx
    return None


class ExecutionJournalHooks(RunHooks[ReplenishmentRunContext]):
    """
    Cross-cutting journal for SDK-mediated tool/model events.

    Primary instrumentation path for Runner.run / run_sync.
    """

    def __init__(self) -> None:
        self._tool_started_at: dict[str, float] = {}
        self._llm_started_at: dict[str, float] = {}
        self._active_turn_id: str | None = None
        self._finished_tool_ids: set[str] = set()
        self._failed_tool_ids: set[str] = set()

    async def on_agent_start(
        self, context: AgentHookContext[ReplenishmentRunContext], agent: Agent[ReplenishmentRunContext]
    ) -> None:
        ctx = _ctx(context)
        if ctx is None:
            return
        logger.info(
            "agent_execution %s",
            json.dumps(
                {
                    "event": "agent_start",
                    "execution_id": ctx.journal_execution_id,
                    "correlation_id": ctx.correlation_id,
                    "agent": getattr(agent, "name", None),
                },
                default=str,
            ),
        )

    async def on_agent_end(
        self,
        context: AgentHookContext[ReplenishmentRunContext],
        agent: Agent[ReplenishmentRunContext],
        output: Any,
    ) -> None:
        ctx = _ctx(context)
        if ctx is None:
            return
        logger.info(
            "agent_execution %s",
            json.dumps(
                {
                    "event": "agent_end",
                    "execution_id": ctx.journal_execution_id,
                    "correlation_id": ctx.correlation_id,
                    "agent": getattr(agent, "name", None),
                    "output_type": type(output).__name__,
                },
                default=str,
            ),
        )

    async def on_llm_start(
        self,
        context: RunContextWrapper[ReplenishmentRunContext],
        agent: Agent[ReplenishmentRunContext],
        system_prompt: str | None,
        input_items: list[Any],
    ) -> None:
        ctx = _ctx(context)
        if ctx is None:
            return
        # Do not persist system_prompt / input_items (may contain sensitive content).
        turn_id = f"MT-{uuid4().hex[:12]}"
        self._active_turn_id = turn_id
        self._llm_started_at[turn_id] = time.perf_counter()
        model_name = getattr(agent, "model", None)
        try:
            record_model_turn_start(
                ctx.journal_execution_id,
                turn_id=turn_id,
                model_name=str(model_name) if model_name else None,
                actor=ctx.actor or "agent",
            )
        except Exception:  # noqa: BLE001 — journaling must not break the run
            logger.exception("on_llm_start journal failed")

    async def on_llm_end(
        self,
        context: RunContextWrapper[ReplenishmentRunContext],
        agent: Agent[ReplenishmentRunContext],
        response: ModelResponse,
    ) -> None:
        ctx = _ctx(context)
        if ctx is None:
            return
        turn_id = self._active_turn_id or f"MT-{uuid4().hex[:12]}"
        started = self._llm_started_at.pop(turn_id, None)
        duration_ms = int((time.perf_counter() - started) * 1000) if started else None
        usage = _usage_from_response(response)
        model_name = getattr(agent, "model", None)
        try:
            record_model_turn_end(
                ctx.journal_execution_id,
                turn_id=turn_id,
                model_name=str(model_name) if model_name else None,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                total_tokens=usage["total_tokens"],
                status="completed",
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            logger.exception("on_llm_end journal failed")
        self._active_turn_id = None

    async def on_tool_start(
        self,
        context: RunContextWrapper[ReplenishmentRunContext],
        agent: Agent[ReplenishmentRunContext],
        tool: Tool,
    ) -> None:
        ctx = _ctx(context)
        if ctx is None:
            return
        tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", "unknown_tool")
        # agents 0.19.1: function tools pass ToolContext with tool_call_id.
        tool_call_id = getattr(context, "tool_call_id", None) or new_tool_call_id()
        args = _parse_tool_arguments(getattr(context, "tool_arguments", None))
        if _ToolContext is not None and not isinstance(context, _ToolContext):
            # Non-function local tools may omit tool_call_id; fallback already applied.
            pass
        try:
            assert_tool_allowed_for_execution(
                str(tool_name),
                execution_type=ctx.execution_type,
                actor_role=ctx.actor_role,
            )
        except Exception as exc:  # noqa: BLE001 — surface as journaled failure then re-raise
            try:
                record_tool_start(
                    ctx.journal_execution_id,
                    tool_name=str(tool_name),
                    input_summary=_sanitize(args),
                    actor=ctx.actor or "agent",
                    tool_call_id=str(tool_call_id),
                )
                record_tool_finish(
                    ctx.journal_execution_id,
                    tool_call_id=str(tool_call_id),
                    status="failed",
                    error=classify_failure(
                        code=getattr(exc, "code", None) or "policy_prohibited",
                        exc=exc,
                        tool_name=str(tool_name),
                    ),
                    actor=ctx.actor or "agent",
                )
                self._failed_tool_ids.add(str(tool_call_id))
            except Exception:  # noqa: BLE001
                logger.exception("failed to journal rejected tool")
            raise

        meta = get_tool_definition(str(tool_name))
        self._tool_started_at[str(tool_call_id)] = time.perf_counter()
        try:
            record_tool_start(
                ctx.journal_execution_id,
                tool_name=str(tool_name),
                input_summary=_sanitize(args),
                actor=ctx.actor or "agent",
                tool_call_id=str(tool_call_id),
            )
            ctx.note_tool(str(tool_name))
            logger.info(
                "agent_execution %s",
                json.dumps(
                    {
                        "event": "tool_start",
                        "execution_id": ctx.journal_execution_id,
                        "correlation_id": ctx.correlation_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "idempotent": meta.idempotent if meta else None,
                    },
                    default=str,
                ),
            )
        except Exception:  # noqa: BLE001
            logger.exception("on_tool_start journal failed")

    async def on_tool_end(
        self,
        context: RunContextWrapper[ReplenishmentRunContext],
        agent: Agent[ReplenishmentRunContext],
        tool: Tool,
        result: object,
    ) -> None:
        ctx = _ctx(context)
        if ctx is None:
            return
        tool_name = getattr(tool, "name", None) or "unknown_tool"
        tool_call_id = getattr(context, "tool_call_id", None)
        if not tool_call_id:
            # Match most recent started entry for this tool if SDK omitted id.
            tool_call_id = self._latest_open_id(str(tool_name)) or new_tool_call_id()
        tid = str(tool_call_id)
        if tid in self._finished_tool_ids or tid in self._failed_tool_ids:
            return
        started = self._tool_started_at.pop(tid, None)
        duration_ms = int((time.perf_counter() - started) * 1000) if started else None
        try:
            record_tool_finish(
                ctx.journal_execution_id,
                tool_call_id=tid,
                status="completed",
                output_summary=_summarize_output(result),
                actor=ctx.actor or "agent",
                duration_ms=duration_ms,
            )
            self._finished_tool_ids.add(tid)
        except Exception:  # noqa: BLE001
            logger.exception("on_tool_end journal failed")

    def journal_tool_failure(
        self,
        *,
        execution_id: str,
        tool_name: str,
        tool_call_id: str | None,
        exc: BaseException,
        actor: str = "agent",
    ) -> None:
        """Secondary path when on_tool_end is skipped due to an exception."""
        tid = str(tool_call_id or new_tool_call_id())
        if tid in self._failed_tool_ids or tid in self._finished_tool_ids:
            return
        started = self._tool_started_at.pop(tid, None)
        duration_ms = int((time.perf_counter() - started) * 1000) if started else None
        try:
            # Ensure a start row exists for correlation.
            record_tool_start(
                execution_id,
                tool_name=tool_name,
                input_summary={},
                actor=actor,
                tool_call_id=tid,
            )
            record_tool_finish(
                execution_id,
                tool_call_id=tid,
                status="failed",
                error=classify_failure(
                    code=getattr(exc, "code", None),
                    exc=exc,
                    tool_name=tool_name,
                ),
                actor=actor,
                duration_ms=duration_ms,
            )
            self._failed_tool_ids.add(tid)
        except Exception:  # noqa: BLE001
            logger.exception("journal_tool_failure failed")

    def _latest_open_id(self, tool_name: str) -> str | None:
        # Prefer in-memory open starts.
        if self._tool_started_at:
            return next(reversed(self._tool_started_at.keys()))
        return None

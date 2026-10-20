"""LLM service façade — used by Agent Runtime only."""

from __future__ import annotations

import logging
from typing import Any

from config import (
    LLM_ENABLE_TOOL_CALLS,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
)
from llm.contracts import ConversationContext, LLMRequest, LLMResponse
from llm.factory import (
    get_llm_orchestrator,
    get_llm_provider,
    llm_provider_health,
    reset_llm_providers,
)
from llm.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def invoke_llm(request: LLMRequest, *, max_retries: int = 0) -> LLMResponse:
    """Agent Runtime entry — never call from business services for domain logic."""
    return get_llm_orchestrator().invoke(request, max_retries=max_retries)


def prepare_runtime_llm_call(
    *,
    workflow: str,
    user_input: str,
    execution_id: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    supplier_id: str | None = None,
    purchase_order_id: str | None = None,
    business_context: dict[str, Any] | None = None,
    tool_context: dict[str, Any] | None = None,
    conversation: ConversationContext | None = None,
    allowed_tools: list[str] | None = None,
    response_schema: dict[str, Any] | None = None,
    invoke: bool = True,
) -> dict[str, Any]:
    """
    Agent Runtime helper: build request, optionally invoke orchestrator,
    return ops summary + response payload.
    """
    registry = ToolRegistry()
    tools = registry.filter_allowed(list(allowed_tools or registry.list_names()))
    request = LLMRequest(
        workflow=workflow,
        user_input=user_input,
        execution_id=execution_id,
        recommendation_id=recommendation_id,
        approval_id=approval_id,
        store_id=store_id,
        sku=sku,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        business_context=dict(business_context or {}),
        tool_context=dict(tool_context or {}),
        conversation=conversation,
        allowed_tools=tools,
        response_schema=response_schema,
        enable_tool_calls=LLM_ENABLE_TOOL_CALLS,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )
    orchestrator = get_llm_orchestrator()
    if not invoke:
        rendered = orchestrator.render_only(request)
        return {
            "invoked": False,
            "provider": LLM_PROVIDER,
            "model": LLM_MODEL,
            "prompt_size_chars": rendered.prompt_size_chars,
            "context_size_chars": rendered.context_size_chars,
            "template_ids": rendered.template_ids,
            "llm_ops": {
                "provider": LLM_PROVIDER,
                "model": LLM_MODEL,
                "prompt_size_chars": rendered.prompt_size_chars,
                "context_size_chars": rendered.context_size_chars,
                "usage": {"input": 0, "output": 0, "total": 0},
                "latency_ms": 0.0,
                "tool_calls": [],
                "tool_call_count": 0,
                "retries": 0,
                "finish_reason": None,
                "validation_ok": True,
                "validation_errors": [],
            },
        }

    response = orchestrator.invoke(request)
    return {
        "invoked": True,
        "provider": response.provider,
        "model": response.model,
        "content": response.content,
        "structured": response.structured,
        "llm_ops": response.to_ops_summary(),
        "response": response,
    }


def attach_llm_to_execution_context(
    context: dict[str, Any] | None,
    *,
    execution_id: str | None = None,
    workflow: str | None = None,
    recommendation_id: str | None = None,
    approval_id: str | None = None,
    store_id: str | None = None,
    sku: str | None = None,
    invoke: bool = False,
) -> dict[str, Any]:
    """
    Enrich execution context with LLM orchestration metadata (fail-soft).

    Default invoke=False attaches config + rendered prompt sizes without a
    live completion (keeps create_execution cheap). Agent Runtime may later
    call prepare_runtime_llm_call(..., invoke=True).
    """
    base = dict(context or {})
    try:
        result = prepare_runtime_llm_call(
            workflow=workflow or str(base.get("mode") or "agent_runtime"),
            user_input=str(
                base.get("goal")
                or base.get("user_input")
                or f"Execution context for {store_id or base.get('store_id')}/{sku or base.get('sku')}"
            ),
            execution_id=execution_id,
            recommendation_id=recommendation_id or base.get("recommendation_id"),
            approval_id=approval_id or base.get("approval_id"),
            store_id=store_id or base.get("store_id"),
            sku=sku or base.get("sku"),
            business_context={
                k: base.get(k)
                for k in ("store_id", "sku", "mode", "question_type")
                if base.get(k) is not None
            },
            invoke=invoke,
        )
        base["llm_ops"] = result.get("llm_ops") or {}
        base["llm_ops"].setdefault("provider", LLM_PROVIDER)
        base["llm_ops"].setdefault("model", LLM_MODEL)
        base["llm_ops"]["timeout_seconds"] = LLM_TIMEOUT
        base["llm_ops"]["max_tokens"] = LLM_MAX_TOKENS
        base["llm_ops"]["temperature"] = LLM_TEMPERATURE
        base["llm_ops"]["tool_calls_enabled"] = LLM_ENABLE_TOOL_CALLS
        if result.get("invoked"):
            base["llm_last_response"] = {
                "content": result.get("content"),
                "structured": result.get("structured"),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_attach_failed execution_id=%s err=%s", execution_id, exc)
        base.setdefault(
            "llm_ops",
            {
                "provider": LLM_PROVIDER,
                "model": LLM_MODEL,
                "prompt_size_chars": 0,
                "context_size_chars": 0,
                "usage": {"input": 0, "output": 0, "total": 0},
                "latency_ms": 0.0,
                "tool_calls": [],
                "tool_call_count": 0,
                "retries": 0,
                "validation_ok": False,
                "validation_errors": ["llm_unavailable"],
                "error": "llm_unavailable",
            },
        )
    return base


def llm_health() -> dict[str, Any]:
    return llm_provider_health()


__all__ = [
    "attach_llm_to_execution_context",
    "get_llm_orchestrator",
    "get_llm_provider",
    "invoke_llm",
    "llm_health",
    "prepare_runtime_llm_call",
    "reset_llm_providers",
]

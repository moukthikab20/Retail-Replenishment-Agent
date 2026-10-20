"""Mock LLM provider — deterministic, no network."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from llm.contracts import LLMRequest, LLMResponse, RenderedPrompt, ToolInvocation
from llm.tokens import TokenEstimator
from llm.types import FinishReason, ToolDomain


class MockLLMProvider:
    """Deterministic provider for tests and offline Agent Runtime."""

    provider_name = "mock"

    def __init__(self, *, model: str = "mock-replenishment-v1") -> None:
        self.model = model
        self._tokens = TokenEstimator()

    def complete(self, request: LLMRequest, *, rendered: RenderedPrompt) -> LLMResponse:
        started = time.perf_counter()
        model = request.model or self.model
        input_tokens = self._tokens.estimate_prompt(rendered)
        structured = {
            "workflow": request.workflow,
            "status": "ok",
            "store_id": request.store_id,
            "sku": request.sku,
            "summary": "Mock orchestration response — no live model called.",
            "echo": (request.user_input or "")[:200],
        }
        if request.response_schema:
            for field in request.response_schema.get("required") or []:
                structured.setdefault(field, None)
            structured["status"] = "ok"

        tool_calls: list[ToolInvocation] = []
        enable_tools = (
            request.enable_tool_calls
            if request.enable_tool_calls is not None
            else True
        )
        if enable_tools and request.allowed_tools:
            # Emit at most one registered tool call for observability tests.
            name = request.allowed_tools[0]
            tool_calls.append(
                ToolInvocation(
                    tool_name=name,
                    domain=ToolDomain.KNOWLEDGE
                    if "memory" in name
                    else ToolDomain.RECOMMENDATION,
                    arguments={"store_id": request.store_id, "sku": request.sku},
                    tool_call_id="mock-tool-1",
                )
            )

        content = json.dumps(structured, default=str)
        output_tokens = self._tokens.estimate_text(content)
        latency = (time.perf_counter() - started) * 1000.0
        return LLMResponse(
            content=content,
            structured=structured,
            provider=self.provider_name,
            model=model,
            finish_reason=FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency,
            prompt_size_chars=rendered.prompt_size_chars,
            context_size_chars=rendered.context_size_chars,
            raw={"mock": True},
            completed_at=datetime.now(timezone.utc),
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_name,
            "model": self.model,
            "message": "Mock LLM provider ready.",
        }

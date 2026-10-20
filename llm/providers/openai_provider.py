"""OpenAI LLM provider — disabled unless configured with an API key."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from config import LLM_MODEL, LLM_TIMEOUT, OPENAI_API_KEY, OPENAI_MODEL
from integrations.failures import ProviderError, ProviderFailureCode
from llm.contracts import LLMRequest, LLMResponse, RenderedPrompt, ToolInvocation
from llm.tokens import TokenEstimator
from llm.types import FinishReason


class OpenAILLMProvider:
    """
    Thin Chat Completions provider.

    Does not implement agent reasoning or OpenAI-specific prompt packs.
    Requires OPENAI_API_KEY; otherwise complete() raises ProviderError.
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else OPENAI_API_KEY) or ""
        self.model = model or LLM_MODEL or OPENAI_MODEL or "gpt-4o-mini"
        self.timeout = float(timeout if timeout is not None else LLM_TIMEOUT)
        self._tokens = TokenEstimator()

    def complete(self, request: LLMRequest, *, rendered: RenderedPrompt) -> LLMResponse:
        if not self.api_key:
            raise ProviderError(
                code=ProviderFailureCode.CONFIG_ERROR.value,
                message=(
                    "OpenAI LLM provider is configured but OPENAI_API_KEY is missing. "
                    "Set the key or use LLM_PROVIDER=mock."
                ),
                provider=self.provider_name,
            )

        started = time.perf_counter()
        model = request.model or self.model
        max_tokens = request.max_tokens
        temperature = request.temperature

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key, timeout=self.timeout)
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": rendered.messages,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            if temperature is not None:
                kwargs["temperature"] = temperature
            completion = client.chat.completions.create(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                code=ProviderFailureCode.PROVIDER_UNAVAILABLE.value,
                message="OpenAI completion failed.",
                provider=self.provider_name,
                details={"error_type": type(exc).__name__},
            ) from exc

        choice = (completion.choices or [None])[0]
        content = ""
        finish_raw = "stop"
        tool_calls: list[ToolInvocation] = []
        if choice is not None:
            message = choice.message
            content = message.content or ""
            finish_raw = str(choice.finish_reason or "stop")
            for tc in message.tool_calls or []:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolInvocation(
                        tool_name=tc.function.name,
                        arguments=args if isinstance(args, dict) else {},
                        tool_call_id=getattr(tc, "id", None),
                    )
                )

        usage = getattr(completion, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) or self._tokens.estimate_prompt(
            rendered
        )
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0) or self._tokens.estimate_text(
            content
        )
        finish = {
            "stop": FinishReason.STOP,
            "tool_calls": FinishReason.TOOL_CALLS,
            "length": FinishReason.LENGTH,
            "content_filter": FinishReason.CONTENT_FILTER,
        }.get(finish_raw, FinishReason.UNKNOWN)

        structured: dict[str, Any] = {}
        if content:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    structured = parsed
            except json.JSONDecodeError:
                structured = {}

        latency = (time.perf_counter() - started) * 1000.0
        return LLMResponse(
            content=content,
            structured=structured,
            provider=self.provider_name,
            model=model,
            finish_reason=finish,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency,
            prompt_size_chars=rendered.prompt_size_chars,
            context_size_chars=rendered.context_size_chars,
            raw={"id": getattr(completion, "id", None)},
            completed_at=datetime.now(timezone.utc),
        )

    def health_check(self) -> dict[str, Any]:
        configured = bool(self.api_key)
        return {
            "ok": configured,
            "provider": self.provider_name,
            "model": self.model,
            "configured": configured,
            "message": (
                "OpenAI provider ready."
                if configured
                else "OpenAI provider disabled — OPENAI_API_KEY not set."
            ),
        }

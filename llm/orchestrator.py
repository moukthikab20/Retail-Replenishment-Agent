"""LLMOrchestrator — Agent Runtime entry for model interaction."""

from __future__ import annotations

import logging
import time
from typing import Any

from config import LLM_ENABLE_TOOL_CALLS, LLM_MAX_TOKENS, LLM_TEMPERATURE
from integrations.failures import ProviderError
from llm.contracts import LLMProvider, LLMRequest, LLMResponse, RenderedPrompt
from llm.observability import record_llm_observability
from llm.prompts.renderer import PromptRenderer
from llm.selector import ModelSelector
from llm.tokens import TokenEstimator
from llm.tools.registry import ToolRegistry
from llm.types import FinishReason
from llm.validator import ResponseValidator

logger = logging.getLogger(__name__)


class LLMOrchestrator:
    """
    Owns prompt assembly, provider invocation, validation, and observability.
    Business services must not call this for domain logic — Agent Runtime does.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        renderer: PromptRenderer | None = None,
        selector: ModelSelector | None = None,
        validator: ResponseValidator | None = None,
        token_estimator: TokenEstimator | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._provider = provider
        self._renderer = renderer or PromptRenderer()
        self._selector = selector or ModelSelector(
            provider=getattr(provider, "provider_name", None)
        )
        self._tools = tool_registry or ToolRegistry()
        self._tokens = token_estimator or TokenEstimator()
        self._validator = validator or ResponseValidator(
            tool_registry=self._tools,
            token_estimator=self._tokens,
            max_tokens=LLM_MAX_TOKENS,
        )

    @property
    def provider_name(self) -> str:
        return getattr(self._provider, "provider_name", "unknown")

    def render_only(self, request: LLMRequest) -> RenderedPrompt:
        memory_context = self._load_memory(request)
        return self._renderer.render(request, memory_context=memory_context)

    def invoke(self, request: LLMRequest, *, max_retries: int = 0) -> LLMResponse:
        started = time.perf_counter()
        retries = 0
        last_error: str | None = None
        response: LLMResponse | None = None

        allowed = self._tools.filter_allowed(list(request.allowed_tools or []))
        if not allowed and request.allowed_tools:
            # Drop hallucinated allow-list entries early
            request = request.model_copy(update={"allowed_tools": []})
        else:
            request = request.model_copy(update={"allowed_tools": allowed})

        if request.enable_tool_calls is None:
            request = request.model_copy(update={"enable_tool_calls": LLM_ENABLE_TOOL_CALLS})
        if request.temperature is None:
            request = request.model_copy(update={"temperature": LLM_TEMPERATURE})
        if request.max_tokens is None:
            request = request.model_copy(update={"max_tokens": LLM_MAX_TOKENS})

        model = self._selector.select(
            requested_model=request.model, workflow=request.workflow
        )
        request = request.model_copy(update={"model": model})

        memory_context = self._load_memory(request)
        rendered = self._renderer.render(request, memory_context=memory_context)

        estimated = self._tokens.estimate_prompt(rendered)
        if self._tokens.would_exceed(estimated, LLM_MAX_TOKENS * 4):
            # Soft warn via validation later; still attempt with truncated note
            logger.warning(
                "llm_prompt_large execution_id=%s estimated_tokens=%s",
                request.execution_id,
                estimated,
            )

        while True:
            try:
                response = self._provider.complete(request, rendered=rendered)
                last_error = None
                break
            except ProviderError as exc:
                last_error = str(exc.message)
                if retries >= max_retries:
                    response = LLMResponse(
                        content="",
                        structured={},
                        provider=self.provider_name,
                        model=model,
                        finish_reason=FinishReason.ERROR,
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        retry_count=retries,
                        prompt_size_chars=rendered.prompt_size_chars,
                        context_size_chars=rendered.context_size_chars,
                        validation_ok=False,
                        validation_errors=[f"provider_error:{last_error}"],
                        raw={"error": last_error},
                    )
                    break
                retries += 1
            except Exception as exc:  # noqa: BLE001
                last_error = type(exc).__name__
                if retries >= max_retries:
                    response = LLMResponse(
                        content="",
                        structured={},
                        provider=self.provider_name,
                        model=model,
                        finish_reason=FinishReason.ERROR,
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        retry_count=retries,
                        prompt_size_chars=rendered.prompt_size_chars,
                        context_size_chars=rendered.context_size_chars,
                        validation_ok=False,
                        validation_errors=[f"provider_error:{last_error}"],
                    )
                    break
                retries += 1

        assert response is not None
        response.retry_count = retries
        response.prompt_size_chars = rendered.prompt_size_chars
        response.context_size_chars = rendered.context_size_chars
        if not response.latency_ms:
            response.latency_ms = (time.perf_counter() - started) * 1000.0

        validation = self._validator.validate(
            response,
            response_schema=request.response_schema,
            allowed_tools=request.allowed_tools,
            provider_error=last_error,
        )
        response.validation_ok = validation.ok
        response.validation_errors = list(validation.errors)

        record_llm_observability(
            response,
            execution_id=request.execution_id,
            workflow=request.workflow,
        )
        return response

    def _load_memory(self, request: LLMRequest) -> dict[str, Any]:
        try:
            from memory.service import assemble_execution_context

            assembled = assemble_execution_context(
                recommendation_id=request.recommendation_id,
                approval_id=request.approval_id,
                purchase_order_id=request.purchase_order_id,
                supplier_id=request.supplier_id,
                store_id=request.store_id,
                sku=request.sku,
                execution_id=request.execution_id,
            )
            return assembled.llm_context
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_memory_attach_failed err=%s", exc)
            return {}

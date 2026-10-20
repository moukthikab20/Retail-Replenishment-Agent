"""Response validation for orchestration outputs."""

from __future__ import annotations

from typing import Any

from llm.contracts import LLMResponse, ValidationResult
from llm.tokens import TokenEstimator
from llm.tools.registry import ToolRegistry
from llm.types import FinishReason, KNOWN_FINISH_REASONS


class ResponseValidator:
    """Validates schema, tools, tokens, finish reasons, and provider errors."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        token_estimator: TokenEstimator | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self._tools = tool_registry or ToolRegistry()
        self._tokens = token_estimator or TokenEstimator()
        self.max_tokens = max_tokens

    def validate(
        self,
        response: LLMResponse,
        *,
        response_schema: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
        provider_error: str | None = None,
    ) -> ValidationResult:
        errors: list[str] = []

        if provider_error:
            errors.append(f"provider_error:{provider_error}")

        finish = response.finish_reason
        if finish not in KNOWN_FINISH_REASONS or finish == FinishReason.UNKNOWN:
            errors.append(f"unknown_finish_reason:{finish}")

        if response.total_tokens and self._tokens.would_exceed(
            response.total_tokens, self.max_tokens
        ):
            errors.append(
                f"token_limit_exceeded:total={response.total_tokens},max={self.max_tokens}"
            )

        allowed = set(allowed_tools or [])
        for call in response.tool_calls:
            if not self._tools.is_registered(call.tool_name):
                errors.append(f"hallucinated_tool:{call.tool_name}")
            elif allowed and call.tool_name not in allowed:
                errors.append(f"tool_not_allowed:{call.tool_name}")

        if response_schema:
            required = list(response_schema.get("required") or [])
            structured = response.structured or {}
            if required and not structured and not response.content:
                errors.append("missing_structured_response")
            for field in required:
                if field not in structured:
                    errors.append(f"missing_field:{field}")

        ok = not errors
        return ValidationResult(ok=ok, errors=errors, finish_reason=finish)

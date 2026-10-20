"""LLM orchestration contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from llm.types import FinishReason, PromptRole, ToolDomain


class PromptTemplate(BaseModel):
    template_id: str
    role: PromptRole
    name: str
    body: str
    version: str = "v1"
    variables: list[str] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    role: str
    content: str
    name: str | None = None


class ConversationContext(BaseModel):
    messages: list[ConversationMessage] = Field(default_factory=list)
    session_id: str | None = None
    conversation_id: str | None = None

    def append(self, role: str, content: str, *, name: str | None = None) -> None:
        self.messages.append(ConversationMessage(role=role, content=content, name=name))


class ToolInvocation(BaseModel):
    tool_name: str
    domain: ToolDomain | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None


class RenderedPrompt(BaseModel):
    messages: list[dict[str, str]] = Field(default_factory=list)
    prompt_size_chars: int = 0
    context_size_chars: int = 0
    template_ids: list[str] = Field(default_factory=list)
    knowledge_sources: list[str] = Field(default_factory=list)


class LLMRequest(BaseModel):
    workflow: str
    user_input: str
    execution_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    store_id: str | None = None
    sku: str | None = None
    supplier_id: str | None = None
    purchase_order_id: str | None = None
    business_context: dict[str, Any] = Field(default_factory=dict)
    tool_context: dict[str, Any] = Field(default_factory=dict)
    conversation: ConversationContext | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enable_tool_calls: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str = ""
    structured: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    finish_reason: FinishReason = FinishReason.STOP
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    retry_count: int = 0
    validation_ok: bool = True
    validation_errors: list[str] = Field(default_factory=list)
    prompt_size_chars: int = 0
    context_size_chars: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None

    def to_ops_summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_size_chars": self.prompt_size_chars,
            "context_size_chars": self.context_size_chars,
            "usage": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "total": self.total_tokens,
            },
            "latency_ms": round(self.latency_ms, 2),
            "tool_calls": [t.tool_name for t in self.tool_calls],
            "tool_call_count": len(self.tool_calls),
            "retries": self.retry_count,
            "finish_reason": str(self.finish_reason),
            "validation_ok": self.validation_ok,
            "validation_errors": list(self.validation_errors),
        }


class ValidationResult(BaseModel):
    ok: bool = True
    errors: list[str] = Field(default_factory=list)
    finish_reason: FinishReason = FinishReason.STOP


class ObservabilityRecord(BaseModel):
    execution_id: str | None = None
    provider: str
    model: str
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    finish_reason: str = "stop"
    retry_count: int = 0
    validation_failures: list[str] = Field(default_factory=list)
    prompt_size_chars: int = 0
    context_size_chars: int = 0
    workflow: str | None = None
    recorded_at: datetime | None = None


@runtime_checkable
class LLMProvider(Protocol):
    provider_name: str

    def complete(self, request: LLMRequest, *, rendered: RenderedPrompt) -> LLMResponse:
        ...

    def health_check(self) -> dict[str, Any]:
        ...


@runtime_checkable
class PromptProvider(Protocol):
    def get_template(self, template_id: str) -> PromptTemplate:
        ...

    def list_templates(self) -> list[PromptTemplate]:
        ...

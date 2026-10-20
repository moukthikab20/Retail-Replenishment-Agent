"""LLM orchestration enums."""

from __future__ import annotations

from enum import StrEnum


class LLMProviderName(StrEnum):
    MOCK = "mock"
    OPENAI = "openai"


class PromptRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    MEMORY = "memory"
    BUSINESS = "business"
    TOOL = "tool"
    CONVERSATION = "conversation"


class ToolDomain(StrEnum):
    INVENTORY = "inventory"
    RECOMMENDATION = "recommendation"
    SUPPLIER = "supplier"
    POLICY = "policy"
    ERP = "erp"
    KNOWLEDGE = "knowledge"
    APPROVAL = "approval"
    AGENT_OPERATIONS = "agent_operations"


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


KNOWN_FINISH_REASONS = frozenset(FinishReason)

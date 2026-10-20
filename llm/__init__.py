"""Enterprise LLM Orchestration Layer.

All model interaction is owned by this package. Business services must not
call providers or construct prompts. Agent Runtime invokes the orchestrator.
"""

from __future__ import annotations

from llm.contracts import (
    ConversationContext,
    LLMRequest,
    LLMResponse,
    PromptTemplate,
    ToolInvocation,
)
from llm.factory import (
    get_llm_orchestrator,
    get_llm_provider,
    reset_llm_providers,
    validate_llm_provider_configuration,
)
from llm.orchestrator import LLMOrchestrator
from llm.service import (
    attach_llm_to_execution_context,
    invoke_llm,
    llm_health,
    prepare_runtime_llm_call,
)
from llm.types import FinishReason, LLMProviderName, PromptRole, ToolDomain

__all__ = [
    "ConversationContext",
    "FinishReason",
    "LLMOrchestrator",
    "LLMProviderName",
    "LLMRequest",
    "LLMResponse",
    "PromptRole",
    "PromptTemplate",
    "ToolDomain",
    "ToolInvocation",
    "attach_llm_to_execution_context",
    "get_llm_orchestrator",
    "get_llm_provider",
    "invoke_llm",
    "llm_health",
    "prepare_runtime_llm_call",
    "reset_llm_providers",
    "validate_llm_provider_configuration",
]

"""Memory provider factory — MEMORY_PROVIDER selection with fail-fast unknown values."""

from __future__ import annotations

from typing import Any

from config import MEMORY_PROVIDER, MEMORY_RETRIEVAL_DEFAULT_LIMIT, MEMORY_RETRIEVAL_MAX_LIMIT
from integrations.failures import ProviderConfigError
from memory.assembler import ContextAssembler
from memory.contracts import KnowledgeProvider, MemoryProvider
from memory.providers.mock import MockMemoryProvider
from memory.providers.sql_provider import DatabaseMemoryProvider
from memory.retrieval import RetrievalEngine

_SUPPORTED: dict[str, type] = {
    "database": DatabaseMemoryProvider,
    "mock": MockMemoryProvider,
}

_memory_provider: MemoryProvider | None = None
_knowledge_provider: KnowledgeProvider | None = None


class DefaultKnowledgeProvider:
    """Knowledge façade wrapping the active MemoryProvider."""

    def __init__(self, memory: MemoryProvider) -> None:
        self._memory = memory
        self.provider_name = getattr(memory, "provider_name", "knowledge")

    def retrieve(self, query):  # type: ignore[no-untyped-def]
        return self._memory.retrieve(query)

    def health_check(self) -> dict[str, Any]:
        base = self._memory.health_check()
        return {
            **base,
            "knowledge_provider": self.provider_name,
            "wraps": getattr(self._memory, "provider_name", None),
        }


def validate_memory_provider_configuration() -> str:
    key = (MEMORY_PROVIDER or "database").strip().lower()
    if key not in _SUPPORTED:
        available = ", ".join(sorted(_SUPPORTED))
        raise ProviderConfigError(
            f"Memory provider '{key}' is not available in this deployment. "
            f"Supported: {available}. Vector backends are not implemented yet.",
            provider_key="memory",
        )
    return key


def get_memory_provider(*, force_new: bool = False) -> MemoryProvider:
    global _memory_provider
    key = validate_memory_provider_configuration()
    if _memory_provider is None or force_new:
        _memory_provider = _SUPPORTED[key]()
    return _memory_provider


def get_knowledge_provider(*, force_new: bool = False) -> KnowledgeProvider:
    global _knowledge_provider
    memory = get_memory_provider(force_new=force_new)
    if _knowledge_provider is None or force_new:
        _knowledge_provider = DefaultKnowledgeProvider(memory)
    return _knowledge_provider


def get_retrieval_engine(*, force_new: bool = False) -> RetrievalEngine:
    provider = get_memory_provider(force_new=force_new)
    return RetrievalEngine(
        provider,
        default_limit=MEMORY_RETRIEVAL_DEFAULT_LIMIT,
        max_limit=MEMORY_RETRIEVAL_MAX_LIMIT,
    )


def get_context_assembler(*, force_new: bool = False) -> ContextAssembler:
    return ContextAssembler(get_retrieval_engine(force_new=force_new))


def reset_memory_providers() -> None:
    global _memory_provider, _knowledge_provider
    _memory_provider = None
    _knowledge_provider = None


def memory_provider_health() -> dict[str, Any]:
    provider = get_memory_provider()
    payload = provider.health_check()
    payload.setdefault("config", (MEMORY_PROVIDER or "database").strip().lower())
    return payload

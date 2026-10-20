"""LLM provider / orchestrator factory — fail-fast unknown providers."""

from __future__ import annotations

from typing import Any

from config import LLM_MODEL, LLM_PROVIDER
from integrations.failures import ProviderConfigError
from llm.contracts import LLMProvider
from llm.orchestrator import LLMOrchestrator
from llm.providers.mock import MockLLMProvider
from llm.providers.openai_provider import OpenAILLMProvider
from llm.selector import ModelSelector

_SUPPORTED: dict[str, type] = {
    "mock": MockLLMProvider,
    "openai": OpenAILLMProvider,
}

_provider: LLMProvider | None = None
_orchestrator: LLMOrchestrator | None = None


def validate_llm_provider_configuration() -> str:
    key = (LLM_PROVIDER or "mock").strip().lower()
    if key not in _SUPPORTED:
        available = ", ".join(sorted(_SUPPORTED))
        raise ProviderConfigError(
            f"LLM provider '{key}' is not available in this deployment. "
            f"Supported: {available}.",
            provider_key="llm",
        )
    return key


def get_llm_provider(*, force_new: bool = False) -> LLMProvider:
    global _provider
    key = validate_llm_provider_configuration()
    if _provider is None or force_new:
        if key == "openai":
            _provider = OpenAILLMProvider(model=LLM_MODEL)
        else:
            _provider = MockLLMProvider(model=LLM_MODEL or "mock-replenishment-v1")
    return _provider


def get_llm_orchestrator(*, force_new: bool = False) -> LLMOrchestrator:
    global _orchestrator
    provider = get_llm_provider(force_new=force_new)
    if _orchestrator is None or force_new:
        _orchestrator = LLMOrchestrator(
            provider,
            selector=ModelSelector(provider=getattr(provider, "provider_name", key_safe())),
        )
    return _orchestrator


def key_safe() -> str:
    try:
        return validate_llm_provider_configuration()
    except ProviderConfigError:
        return "mock"


def reset_llm_providers() -> None:
    global _provider, _orchestrator
    _provider = None
    _orchestrator = None


def llm_provider_health() -> dict[str, Any]:
    provider = get_llm_provider()
    payload = provider.health_check()
    payload.setdefault("config", (LLM_PROVIDER or "mock").strip().lower())
    payload.setdefault("model", LLM_MODEL)
    return payload

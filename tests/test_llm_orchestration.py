"""Enterprise LLM Orchestration Layer tests."""

from __future__ import annotations

import pytest

from agent.execution_engine import create_execution
from agent.execution_states import ExecutionType
from integrations.failures import ProviderConfigError, ProviderError
from llm.contracts import ConversationContext, LLMRequest, LLMResponse, ToolInvocation
from llm.factory import (
    get_llm_orchestrator,
    get_llm_provider,
    reset_llm_providers,
    validate_llm_provider_configuration,
)
from llm.observability import list_llm_observability, reset_llm_observability
from llm.prompts.provider import CatalogPromptProvider
from llm.prompts.renderer import PromptRenderer
from llm.providers.mock import MockLLMProvider
from llm.providers.openai_provider import OpenAILLMProvider
from llm.selector import ModelSelector
from llm.service import attach_llm_to_execution_context, invoke_llm, prepare_runtime_llm_call
from llm.tokens import TokenEstimator
from llm.tools.registry import ToolRegistry, execute_registered_tool
from llm.types import FinishReason, ToolDomain
from llm.validator import ResponseValidator
from services import agent_ops_service


def test_unknown_provider_fails_fast(monkeypatch):
    monkeypatch.setattr("config.LLM_PROVIDER", "anthropic")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "anthropic")
    reset_llm_providers()
    with pytest.raises(ProviderConfigError):
        validate_llm_provider_configuration()
    with pytest.raises(ProviderConfigError):
        get_llm_provider(force_new=True)


def test_provider_selection_mock_and_openai(monkeypatch):
    monkeypatch.setattr("config.LLM_PROVIDER", "mock")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "mock")
    reset_llm_providers()
    assert isinstance(get_llm_provider(force_new=True), MockLLMProvider)

    monkeypatch.setattr("config.LLM_PROVIDER", "openai")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "openai")
    reset_llm_providers()
    assert isinstance(get_llm_provider(force_new=True), OpenAILLMProvider)


def test_mock_provider_complete():
    provider = MockLLMProvider()
    request = LLMRequest(
        workflow="test",
        user_input="hello",
        store_id="ST001",
        sku="SKU-1001",
        allowed_tools=["get_inventory_position"],
        response_schema={"required": ["status", "summary"]},
    )
    rendered = PromptRenderer().render(request, memory_context={})
    response = provider.complete(request, rendered=rendered)
    assert response.provider == "mock"
    assert response.structured.get("status") == "ok"
    assert response.total_tokens >= 0
    assert provider.health_check()["ok"] is True


def test_openai_provider_disabled_without_key(monkeypatch):
    monkeypatch.setattr("llm.providers.openai_provider.OPENAI_API_KEY", "")
    provider = OpenAILLMProvider(api_key="")
    request = LLMRequest(workflow="test", user_input="hi")
    rendered = PromptRenderer().render(request)
    with pytest.raises(ProviderError):
        provider.complete(request, rendered=rendered)
    assert provider.health_check()["ok"] is False


def test_prompt_rendering_includes_roles():
    provider = CatalogPromptProvider()
    assert provider.get_template("system.default").role.value == "system"
    renderer = PromptRenderer(provider)
    conversation = ConversationContext()
    conversation.append("user", "Why this quantity?")
    request = LLMRequest(
        workflow="follow_up",
        user_input="Explain recommendation",
        store_id="ST001",
        sku="SKU-1001",
        recommendation_id="REC-1",
        business_context={"risk": "medium"},
        tool_context={"last_tool": "get_recommendation"},
        conversation=conversation,
        allowed_tools=["get_recommendation"],
    )
    rendered = renderer.render(
        request,
        memory_context={"knowledge_sources": ["mock"], "memory": {}},
    )
    assert rendered.prompt_size_chars > 0
    assert rendered.context_size_chars > 0
    assert "system.default" in rendered.template_ids
    assert "user.default" in rendered.template_ids
    assert "memory.context" in rendered.template_ids
    assert "business.context" in rendered.template_ids
    assert "tool.context" in rendered.template_ids
    assert "conversation.context" in rendered.template_ids
    roles = {m["role"] for m in rendered.messages}
    assert "system" in roles and "user" in roles


def test_tool_registry_domains_and_hallucination_gate():
    registry = ToolRegistry()
    assert registry.is_registered("get_inventory_position")
    assert registry.get("get_inventory_position").domain == ToolDomain.INVENTORY
    assert registry.list_tools(domain=ToolDomain.APPROVAL)
    assert registry.list_tools(domain=ToolDomain.ERP)
    assert registry.list_tools(domain=ToolDomain.AGENT_OPERATIONS)
    with pytest.raises(ValueError, match="Hallucinated"):
        registry.assert_registered("invent_quantity")
    assert registry.filter_allowed(["get_recommendation", "fake_tool"]) == [
        "get_recommendation"
    ]


def test_execute_registered_knowledge_tool():
    out = execute_registered_tool(
        "retrieve_related_memory",
        {"store_id": "ST001", "sku": "SKU-1001"},
    )
    assert "record_count" in out


def test_response_validation():
    validator = ResponseValidator(max_tokens=100)
    good = LLMResponse(
        content="{}",
        structured={"status": "ok", "summary": "fine"},
        provider="mock",
        model="m",
        finish_reason=FinishReason.STOP,
        total_tokens=10,
        tool_calls=[
            ToolInvocation(tool_name="get_inventory_position", arguments={}),
        ],
    )
    result = validator.validate(
        good,
        response_schema={"required": ["status", "summary"]},
        allowed_tools=["get_inventory_position"],
    )
    assert result.ok is True

    bad = LLMResponse(
        content="",
        structured={},
        provider="mock",
        model="m",
        finish_reason=FinishReason.UNKNOWN,
        total_tokens=5000,
        tool_calls=[ToolInvocation(tool_name="hallucinated_tool")],
    )
    failed = validator.validate(
        bad,
        response_schema={"required": ["status"]},
        allowed_tools=["get_inventory_position"],
        provider_error="timeout",
    )
    assert failed.ok is False
    joined = " ".join(failed.errors)
    assert "provider_error" in joined
    assert "unknown_finish_reason" in joined
    assert "token_limit_exceeded" in joined
    assert "hallucinated_tool" in joined
    assert "missing_field:status" in joined


def test_token_estimation():
    est = TokenEstimator(chars_per_token=4.0)
    assert est.estimate_text("abcd") == 1
    assert est.would_exceed(5000, 100) is True
    request = LLMRequest(workflow="t", user_input="x" * 40)
    rendered = PromptRenderer().render(request)
    assert est.estimate_prompt(rendered) >= 1


def test_model_selector():
    selector = ModelSelector(provider="mock", default_model="mock-base")
    assert selector.select(workflow="follow_up") == "mock-follow_up-v1"
    assert selector.select(requested_model="custom") == "custom"
    assert "provider" in selector.snapshot()


def test_conversation_assembly_and_orchestrator_invoke(monkeypatch):
    monkeypatch.setattr("config.LLM_PROVIDER", "mock")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "mock")
    reset_llm_providers()
    reset_llm_observability()
    conversation = ConversationContext()
    conversation.append("user", "prior question")
    conversation.append("assistant", "prior answer")
    request = LLMRequest(
        workflow="follow_up",
        user_input="continue",
        store_id="ST001",
        sku="SKU-1001",
        conversation=conversation,
        allowed_tools=["get_recommendation", "retrieve_related_memory"],
        response_schema={"required": ["status", "summary"]},
        execution_id="EXE-LLM-1",
    )
    response = invoke_llm(request)
    assert response.provider == "mock"
    assert response.validation_ok is True
    assert response.prompt_size_chars > 0
    audits = list_llm_observability(limit=10)
    assert audits
    assert audits[-1]["execution_id"] == "EXE-LLM-1"
    assert "latency_ms" in audits[-1]
    assert "tool_calls" in audits[-1]


def test_prepare_runtime_and_attach(monkeypatch):
    monkeypatch.setattr("config.LLM_PROVIDER", "mock")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "mock")
    reset_llm_providers()
    prepared = prepare_runtime_llm_call(
        workflow="recommendation_analysis",
        user_input="Analyze ST001/SKU-1001",
        store_id="ST001",
        sku="SKU-1001",
        invoke=True,
        allowed_tools=["get_inventory_position"],
        response_schema={"required": ["status"]},
    )
    assert prepared["invoked"] is True
    assert prepared["llm_ops"]["provider"] == "mock"
    assert "usage" in prepared["llm_ops"]

    attached = attach_llm_to_execution_context(
        {"store_id": "ST001", "sku": "SKU-1001"},
        execution_id="EXE-ATT-LLM",
        workflow="recommendation_analysis",
        invoke=False,
    )
    assert "llm_ops" in attached
    assert attached["llm_ops"]["prompt_size_chars"] >= 0


def test_create_execution_exposes_llm_ops(monkeypatch):
    monkeypatch.setattr("config.LLM_PROVIDER", "mock")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "mock")
    reset_llm_providers()
    ex = create_execution(
        execution_type=ExecutionType.RECOMMENDATION_ANALYSIS,
        goal="llm ops visibility",
        context={"store_id": "ST001", "sku": "SKU-1001"},
    )
    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    llm = detail.get("llm")
    assert isinstance(llm, dict)
    assert llm.get("provider") == "mock"
    assert "model" in llm
    assert "prompt_size_chars" in llm
    assert "context_size_chars" in llm
    assert "usage" in llm
    assert "latency_ms" in llm
    assert "tool_calls" in llm
    assert "retries" in llm
    assert "validation_ok" in llm or llm.get("validation_ok") is None


def test_orchestrator_rejects_unregistered_tools_in_allow_list(monkeypatch):
    monkeypatch.setattr("config.LLM_PROVIDER", "mock")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "mock")
    reset_llm_providers()
    orch = get_llm_orchestrator(force_new=True)
    response = orch.invoke(
        LLMRequest(
            workflow="test",
            user_input="x",
            allowed_tools=["get_inventory_position", "not_a_real_tool"],
            response_schema={"required": ["status"]},
        )
    )
    # Hallucinated allow-list entry filtered before call; response validates.
    assert all(t.tool_name != "not_a_real_tool" for t in response.tool_calls)

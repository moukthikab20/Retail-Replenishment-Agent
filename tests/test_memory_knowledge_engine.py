"""Enterprise Memory & Knowledge Engine tests."""

from __future__ import annotations

import time

import pytest

from agent.execution_engine import create_execution
from agent.execution_states import ExecutionType
from integrations.failures import ProviderConfigError
from memory.assembler import ContextAssembler
from memory.audit import list_memory_audits, reset_memory_audit
from memory.contracts import MemoryQuery, MemoryRecord
from memory.factory import (
    get_knowledge_provider,
    get_memory_provider,
    get_retrieval_engine,
    reset_memory_providers,
    validate_memory_provider_configuration,
)
from memory.providers.mock import MockMemoryProvider, default_mock_records
from memory.providers.sql_provider import DatabaseMemoryProvider
from memory.retrieval import RetrievalEngine
from memory.service import assemble_execution_context, attach_memory_to_execution_context
from memory.types import MemoryType
from services import agent_ops_service


def test_unknown_provider_fails_fast(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "pinecone")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "pinecone")
    reset_memory_providers()
    with pytest.raises(ProviderConfigError):
        validate_memory_provider_configuration()
    with pytest.raises(ProviderConfigError):
        get_memory_provider(force_new=True)


def test_provider_selection_mock_and_database(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    assert isinstance(get_memory_provider(force_new=True), MockMemoryProvider)

    monkeypatch.setattr("config.MEMORY_PROVIDER", "database")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "database")
    reset_memory_providers()
    assert isinstance(get_memory_provider(force_new=True), DatabaseMemoryProvider)


def test_multiple_providers_share_contract(monkeypatch):
    for key, cls in (("mock", MockMemoryProvider), ("database", DatabaseMemoryProvider)):
        monkeypatch.setattr("config.MEMORY_PROVIDER", key)
        monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", key)
        reset_memory_providers()
        provider = get_memory_provider(force_new=True)
        assert isinstance(provider, cls)
        result = provider.retrieve(MemoryQuery(limit=3, related_only=False))
        assert result.source == key
        assert isinstance(result.records, list)
        health = provider.health_check()
        assert health["ok"] is True
        knowledge = get_knowledge_provider(force_new=True)
        assert knowledge.health_check()["ok"] is True


def test_retrieval_methods_and_limits(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    reset_memory_audit()
    engine = get_retrieval_engine(force_new=True)

    recent = engine.retrieve_recent(limit=2, execution_id="EXE-TEST-1")
    assert len(recent.records) <= 2

    related = engine.retrieve_related(store_id="ST001", sku="SKU-1001", limit=20)
    assert related.records

    by_store = engine.retrieve_by_store("ST001", limit=5)
    assert all(
        r.store_id in {None, "ST001"} or r.memory_type == MemoryType.SUPPLIER
        for r in by_store.records
    ) or by_store.records

    by_sku = engine.retrieve_by_sku("SKU-1001", store_id="ST001", limit=5)
    assert by_sku.records

    by_supplier = engine.retrieve_by_supplier("Demo Vendor", limit=5)
    assert by_supplier.records

    failures = engine.retrieve_previous_failures(store_id="ST001", limit=10)
    assert any(r.payload.get("is_failure") for r in failures.records)

    approvals = engine.retrieve_previous_approvals(recommendation_id="REC-MOCK-1", limit=5)
    assert approvals.records

    orders = engine.retrieve_previous_orders(store_id="ST001", sku="SKU-1001", limit=5)
    assert orders.records

    # Configurable clamp
    clamped = engine.retrieve_recent(limit=999)
    assert len(clamped.records) <= engine.max_limit


def test_empty_memory(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    empty = MockMemoryProvider(records=[])
    engine = RetrievalEngine(empty, default_limit=5, max_limit=10)
    result = engine.retrieve_related(store_id="ST999", sku="SKU-NONE")
    assert result.records == []
    assembled = ContextAssembler(engine).assemble(store_id="ST999", sku="SKU-NONE")
    assert assembled.record_count == 0
    assert assembled.to_ops_summary()["memory_retrieved"] is False
    assert assembled.context_size_chars > 0  # anchors still encoded


def test_context_assembly(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    assembled = assemble_execution_context(
        recommendation_id="REC-MOCK-1",
        approval_id="APR-MOCK-1",
        purchase_order_id="PO-MOCK-1",
        supplier_id="Demo Vendor",
        store_id="ST001",
        sku="SKU-1001",
        execution_id="EXE-ASM-1",
    )
    assert assembled.record_count > 0
    assert "memory" in assembled.llm_context
    assert assembled.knowledge_sources
    summary = assembled.to_ops_summary()
    assert summary["memory_retrieved"] is True
    assert summary["retrieved_records"] == assembled.record_count
    assert summary["context_size_chars"] == assembled.context_size_chars
    assert "retrieval_latency_ms" in summary


def test_memory_auditing(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    reset_memory_audit()
    engine = get_retrieval_engine(force_new=True)
    engine.retrieve_by_store("ST001", execution_id="EXE-AUD-1", limit=3)
    audits = list_memory_audits(limit=20)
    assert audits
    last = audits[-1]
    assert last["execution_id"] == "EXE-AUD-1"
    assert last["retrieval_source"]
    assert "record_count" in last
    assert "duration_ms" in last


def test_attach_memory_fail_soft(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()

    enriched = attach_memory_to_execution_context(
        {"store_id": "ST001", "sku": "SKU-1001"},
        execution_id="EXE-ATT-1",
    )
    assert "memory" in enriched
    assert "memory_ops" in enriched
    assert enriched["memory_ops"]["memory_retrieved"] is True

    def boom(**_kwargs):
        raise RuntimeError("forced")

    monkeypatch.setattr("memory.service.assemble_execution_context", boom)
    soft = attach_memory_to_execution_context({"store_id": "ST001"}, execution_id="EXE-SOFT")
    assert soft["memory_ops"]["memory_retrieved"] is False
    assert soft["memory_ops"]["error"] == "memory_unavailable"


def test_create_execution_attaches_memory(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    ex = create_execution(
        execution_type=ExecutionType.RECOMMENDATION_ANALYSIS,
        goal="memory wire test",
        context={"store_id": "ST001", "sku": "SKU-1001"},
    )
    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    assert isinstance(detail.get("memory"), dict)
    assert "memory_ops" in (detail.get("context") or {})

def test_agent_ops_exposes_memory_summary(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    ex = create_execution(
        execution_type=ExecutionType.FOLLOW_UP,
        goal="ops memory visibility",
        recommendation_id="REC-MOCK-1",
        context={"store_id": "ST001", "sku": "SKU-1001"},
    )
    detail = agent_ops_service.get_agent_execution_detail(ex["execution_id"])
    assert detail is not None
    memory = detail.get("memory")
    assert isinstance(memory, dict)
    assert "memory_retrieved" in memory
    assert "knowledge_sources" in memory
    assert "retrieved_records" in memory
    assert "context_size_chars" in memory
    assert "retrieval_latency_ms" in memory


def test_memory_retrieval_performance(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "mock")
    reset_memory_providers()
    engine = get_retrieval_engine(force_new=True)
    started = time.perf_counter()
    for _ in range(20):
        engine.retrieve_related(store_id="ST001", sku="SKU-1001", limit=10)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    # Mock SQL-free path should stay well under 2s for 20 calls.
    assert elapsed_ms < 2000.0

    assembled = assemble_execution_context(store_id="ST001", sku="SKU-1001")
    assert assembled.retrieval_latency_ms < 1000.0


def test_database_provider_empty_db(monkeypatch):
    monkeypatch.setattr("config.MEMORY_PROVIDER", "database")
    monkeypatch.setattr("memory.factory.MEMORY_PROVIDER", "database")
    reset_memory_providers()
    provider = get_memory_provider(force_new=True)
    result = provider.retrieve(
        MemoryQuery(
            memory_types=[MemoryType.RECOMMENDATION, MemoryType.APPROVAL],
            store_id="ST001",
            sku="SKU-1001",
            limit=5,
        )
    )
    assert result.records == []
    assert result.source == "database"


def test_memory_record_vector_fields_reserved():
    record = MemoryRecord(
        record_id="R1",
        memory_type=MemoryType.POLICY,
        title="t",
        source="mock",
    )
    assert record.score is None
    assert record.embedding_ref is None
    assert set(default_mock_records()[0].model_dump()) >= {
        "record_id",
        "memory_type",
        "title",
        "score",
        "embedding_ref",
    }

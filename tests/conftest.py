"""Shared pytest fixtures."""

from __future__ import annotations

import enum
import sys

# Python 3.10 compatibility: enum.StrEnum is 3.11+.
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum  # type: ignore[attr-defined]
    sys.modules["enum"].StrEnum = StrEnum  # type: ignore[attr-defined]

import pytest

from database.connection import init_db, reset_engine
from integrations.factory import reset_providers
from llm.factory import reset_llm_providers
from llm.observability import reset_llm_observability
from memory.audit import reset_memory_audit
from memory.factory import reset_memory_providers
from memory.rag.embeddings import reset_embedding_provider
from memory.rag.vector_store import reset_vector_store
from planner.audit import reset_plan_audit
from planner.factory import reset_planner
from decision.audit import reset_decision_audit
from decision.factory import reset_decision_engine
from workflow.audit import reset_workflow_audit
from workflow.factory import reset_workflow_engine
from eventbus.factory import reset_event_bus
from repositories.csv_repository import clear_csv_cache
from services.auth_service import reset_auth_state


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_retail_agent.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("config.DATABASE_URL", url)
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    # Fast deterministic memory for the suite; tests can override to database.
    monkeypatch.setenv("MEMORY_PROVIDER", "mock")
    monkeypatch.setattr("config.MEMORY_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_AUDIT_PERSIST", "false")
    monkeypatch.setattr("config.MEMORY_AUDIT_PERSIST", False)
    monkeypatch.setattr("memory.audit.MEMORY_AUDIT_PERSIST", False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr("config.LLM_PROVIDER", "mock")
    monkeypatch.setattr("llm.factory.LLM_PROVIDER", "mock")
    monkeypatch.setenv("PLANNER_PROVIDER", "mock")
    monkeypatch.setattr("config.PLANNER_PROVIDER", "mock")
    monkeypatch.setattr("planner.factory.PLANNER_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")
    monkeypatch.setattr("config.EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setattr("config.RAG_ENABLED", True)
    monkeypatch.setattr("memory.rag.search.RAG_ENABLED", True)
    monkeypatch.setenv("DECISION_ENABLED", "true")
    monkeypatch.setattr("config.DECISION_ENABLED", True)
    monkeypatch.setenv("DECISION_STRATEGY", "balanced")
    monkeypatch.setattr("config.DECISION_STRATEGY", "balanced")
    monkeypatch.setenv("DECISION_LLM_ADVISOR", "false")
    monkeypatch.setattr("config.DECISION_LLM_ADVISOR", False)
    monkeypatch.setenv("WORKFLOW_ENABLED", "true")
    monkeypatch.setattr("config.WORKFLOW_ENABLED", True)
    monkeypatch.setenv("WORKFLOW_CHECKPOINTS_ENABLED", "true")
    monkeypatch.setattr("config.WORKFLOW_CHECKPOINTS_ENABLED", True)
    monkeypatch.setenv("WORKFLOW_COMPENSATION_ENABLED", "false")
    monkeypatch.setattr("config.WORKFLOW_COMPENSATION_ENABLED", False)
    monkeypatch.setenv("EVENT_ENABLED", "true")
    monkeypatch.setattr("config.EVENT_ENABLED", True)
    monkeypatch.setenv("EVENT_PROVIDER", "in_process")
    monkeypatch.setattr("config.EVENT_PROVIDER", "in_process")
    monkeypatch.setenv("EVENT_SYNC_DISPATCH", "true")
    monkeypatch.setattr("config.EVENT_SYNC_DISPATCH", True)
    monkeypatch.setenv("EVENT_DEAD_LETTER", "true")
    monkeypatch.setattr("config.EVENT_DEAD_LETTER", True)
    reset_engine()
    reset_providers()
    reset_memory_providers()
    reset_memory_audit()
    reset_llm_providers()
    reset_llm_observability()
    reset_planner()
    reset_plan_audit()
    reset_decision_engine()
    reset_decision_audit()
    reset_workflow_engine()
    reset_workflow_audit()
    reset_event_bus()
    reset_embedding_provider()
    reset_vector_store()
    reset_auth_state()
    init_db(url)
    clear_csv_cache()
    yield
    reset_auth_state()
    reset_providers()
    reset_memory_providers()
    reset_memory_audit()
    reset_llm_providers()
    reset_llm_observability()
    reset_planner()
    reset_plan_audit()
    reset_decision_engine()
    reset_decision_audit()
    reset_workflow_engine()
    reset_workflow_audit()
    reset_event_bus()
    reset_embedding_provider()
    reset_vector_store()
    reset_engine()
    clear_csv_cache()

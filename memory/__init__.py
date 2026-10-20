"""Enterprise Memory & Knowledge Engine.

SQL-backed today; architecture is vector-store ready (Azure AI Search /
OpenSearch / pgvector / Pinecone) without changing business services.
"""

from __future__ import annotations

from memory.assembler import ContextAssembler
from memory.contracts import AssembledContext, MemoryQuery, MemoryRecord, RetrievalResult
from memory.factory import (
    get_knowledge_provider,
    get_memory_provider,
    reset_memory_providers,
    validate_memory_provider_configuration,
)
from memory.retrieval import RetrievalEngine
from memory.service import (
    assemble_execution_context,
    memory_health,
    retrieve_related_memory,
)
from memory.types import MemoryType

__all__ = [
    "AssembledContext",
    "ContextAssembler",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryType",
    "RetrievalEngine",
    "RetrievalResult",
    "assemble_execution_context",
    "get_knowledge_provider",
    "get_memory_provider",
    "memory_health",
    "reset_memory_providers",
    "retrieve_related_memory",
    "validate_memory_provider_configuration",
]

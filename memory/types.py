"""Memory type catalog."""

from __future__ import annotations

from enum import StrEnum


class MemoryType(StrEnum):
    EXECUTION = "execution"
    DECISION = "decision"
    APPROVAL = "approval"
    RECOMMENDATION = "recommendation"
    SUPPLIER = "supplier"
    INVENTORY = "inventory"
    ERP = "erp"
    CONVERSATION = "conversation"
    POLICY = "policy"
    KNOWLEDGE = "knowledge"


ALL_MEMORY_TYPES: tuple[MemoryType, ...] = tuple(MemoryType)

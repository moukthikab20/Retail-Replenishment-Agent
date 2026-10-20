"""Run context shared with agent tools — never store secrets here."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReplenishmentRunContext:
    """
    Non-sensitive orchestration context for a single agent run.

    Authoritative approvals/orders live in the database, not in this object
    or in agent session memory.
    """

    run_id: str
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    actor: str = "agent"
    actor_role: str | None = None
    recommendation_id: str | None = None
    tools_used: list[str] = field(default_factory=list)
    # Durable execution journal keys (additive).
    execution_id: str | None = None
    correlation_id: str | None = None
    approval_id: str | None = None
    execution_type: str | None = None

    def note_tool(self, name: str) -> None:
        if name not in self.tools_used:
            self.tools_used.append(name)

    @property
    def journal_execution_id(self) -> str:
        """Authoritative key for the persistent execution journal."""
        return self.execution_id or self.run_id

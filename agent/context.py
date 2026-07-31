"""Run context shared with agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReplenishmentRunContext:
    run_id: str
    actor: str = "agent"
    actor_role: str | None = None
    tools_used: list[str] = field(default_factory=list)
    recommendation_id: str | None = None

    def note_tool(self, name: str) -> None:
        if name not in self.tools_used:
            self.tools_used.append(name)

"""Single Retail Replenishment Agent definition."""

from __future__ import annotations

from agents import Agent

from agent.instructions import AGENT_INSTRUCTIONS, AGENT_NAME
from agent.schemas import ReplenishmentAgentDecision
from agent.tools import ALL_TOOLS
from config import OPENAI_MODEL


def build_replenishment_agent(model: str | None = None) -> Agent:
    return Agent(
        name=AGENT_NAME,
        instructions=AGENT_INSTRUCTIONS,
        tools=ALL_TOOLS,
        output_type=ReplenishmentAgentDecision,
        model=model or OPENAI_MODEL,
    )

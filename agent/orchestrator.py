"""Single Retail Replenishment Agent definition."""

from __future__ import annotations

from agents import Agent

from agent.instructions import (
    AGENT_INSTRUCTIONS,
    AGENT_NAME,
    ANALYSIS_FORBIDDEN_DURING_ANALYSIS,
    ANALYSIS_TOOL_SEQUENCE,
    FOLLOW_UP_INSTRUCTIONS,
)
from agent.follow_up_guardrails import FOLLOW_UP_INPUT_GUARDRAILS
from agent.schemas import FollowUpAnswer, ReplenishmentAgentDecision
from agent.tools import ALL_TOOLS, FOLLOW_UP_TOOLS
from config import AGENT_MAX_TURNS, FOLLOW_UP_MAX_TURNS, OPENAI_MODEL


def build_replenishment_agent(
    model: str | None = None,
    *,
    output_type: type | None = None,
    tools: list | None = None,
    instructions: str | None = None,
    input_guardrails: list | None = None,
) -> Agent:
    """
    Build the one Retail Replenishment Agent.

    Model and turn limits come from environment-backed config unless a test
    explicitly overrides the model argument. Follow-up runs reuse this agent
    with FollowUpAnswer output, FOLLOW_UP_TOOLS, and FOLLOW_UP_INSTRUCTIONS.
    """
    return Agent(
        name=AGENT_NAME,
        instructions=instructions if instructions is not None else AGENT_INSTRUCTIONS,
        tools=tools if tools is not None else ALL_TOOLS,
        output_type=output_type or ReplenishmentAgentDecision,
        model=model or OPENAI_MODEL,
        input_guardrails=input_guardrails or [],
    )


def build_follow_up_agent(model: str | None = None) -> Agent:
    """Same single agent configured for follow-up Q&A (not a separate specialist)."""
    return build_replenishment_agent(
        model=model,
        output_type=FollowUpAnswer,
        tools=FOLLOW_UP_TOOLS,
        instructions=FOLLOW_UP_INSTRUCTIONS,
        input_guardrails=FOLLOW_UP_INPUT_GUARDRAILS,
    )


def analysis_max_turns() -> int:
    """Finite turn budget for analysis / order workflows."""
    return AGENT_MAX_TURNS


def follow_up_max_turns() -> int:
    """Finite turn budget for follow-up Q&A (typically 6–8)."""
    return FOLLOW_UP_MAX_TURNS


def required_analysis_tools() -> tuple[str, ...]:
    return ANALYSIS_TOOL_SEQUENCE


def forbidden_analysis_tools() -> tuple[str, ...]:
    return ANALYSIS_FORBIDDEN_DURING_ANALYSIS

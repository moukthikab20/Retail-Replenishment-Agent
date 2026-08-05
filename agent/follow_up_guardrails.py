"""Input and tool guardrails for follow-up Q&A.

Blocks chat attempts to mutate business state, approve/order, or request
dangerous actions. Scenario tools get input validation guardrails.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    ToolGuardrailFunctionOutput,
    input_guardrail,
    tool_input_guardrail,
)
from agents.tool_guardrails import ToolInputGuardrailData

FOLLOW_UP_PROHIBITED_NEXT_ACTION = "Use the Review and Formal Approval workflow."

_PROHIBITION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "follow_up_approval_forbidden",
        (
            r"\bplease approve\b",
            r"\bapprove (this|the|it|recommendation|order|request)\b",
            r"\bapprove it\b",
            r"\bgo ahead and approve\b",
            r"\bgo ahead\b",
            r"\bmark (this|it|the recommendation) as approved\b",
            r"\bformally approve\b",
            r"\breject\b.{0,40}\bapproval\b",
            r"\bdeny\b.{0,40}\bapproval\b",
        ),
    ),
    (
        "follow_up_order_forbidden",
        (
            r"\bcreate (a )?(mock )?purchase order\b",
            r"\bcreate (the )?po\b",
            r"\bplace (the |this )?order\b",
            r"\bplace (the |this )?order now\b",
            r"\bcreate_mock_purchase_order\b",
            r"\bsubmit (the |this )?purchase order\b",
            r"\bgenerate (a |the )?purchase order\b",
        ),
    ),
    (
        "follow_up_mutation_forbidden",
        (
            r"\bedit (the )?database\b",
            r"\bupdate (the )?database\b",
            r"\bdelete from\b",
            r"\bdrop table\b",
            r"\bmodify (the )?stored recommendation\b",
            r"\bchange (the )?stored recommendation\b",
            r"\boverwrite (the )?recommendation\b",
            r"\bupdate (the )?saved recommendation\b",
            r"\bset agent_recommended_quantity\b",
            r"\bchange agent_recommended_quantity\b",
            r"\bpersist (this|the) (quantity|change)\b",
            r"\bsave (this|the) (quantity|override) (to|as) (the )?recommendation\b",
        ),
    ),
    (
        "follow_up_role_bypass_forbidden",
        (
            r"\bbypass (role|roles|permission|permissions|authorization|authz)\b",
            r"\bignore (role|roles|permission|permissions)\b",
            r"\bas administrator\b",
            r"\belevate (my )?role\b",
            r"\bskip (the )?approval\b",
        ),
    ),
    (
        "follow_up_secrets_forbidden",
        (
            r"\bapi[ _-]?key\b",
            r"\bopenai_api_key\b",
            r"\bdemo_access_code\b",
            r"\baccess code\b",
            r"\bpassword\b",
            r"\bsecret(s)?\b",
            r"\bauthorization token\b",
            r"\bdatabase_url\b",
        ),
    ),
    (
        "follow_up_sql_forbidden",
        (
            r"\bselect\s+.+\s+from\b",
            r"\binsert\s+into\b",
            r"\bupdate\s+\w+\s+set\b",
            r"\bdelete\s+from\b",
            r"\bexecute\s+sql\b",
            r"\brun\s+sql\b",
            r"\barbitrary sql\b",
            r"\braw sql\b",
        ),
    ),
    (
        "follow_up_external_url_forbidden",
        (
            r"https?://",
            r"\bcurl\b",
            r"\bwget\b",
            r"\bfetch (from )?(url|https?)\b",
            r"\bcall (an? )?external (url|api|endpoint)\b",
            r"\bopen (this |the )?url\b",
        ),
    ),
)

_MESSAGES = {
    "follow_up_approval_forbidden": (
        "Follow-up chat cannot approve or reject approvals. "
        "Use the Review and Formal Approval workflow."
    ),
    "follow_up_order_forbidden": (
        "Follow-up chat cannot create a purchase order. "
        "Use the Review and Formal Approval workflow."
    ),
    "follow_up_mutation_forbidden": (
        "Follow-up chat cannot edit database records or modify the stored recommendation. "
        "Use the Review and Formal Approval workflow."
    ),
    "follow_up_role_bypass_forbidden": (
        "Follow-up chat cannot bypass role requirements. "
        "Use the Review and Formal Approval workflow."
    ),
    "follow_up_secrets_forbidden": (
        "Follow-up chat cannot disclose secrets or credentials. "
        "Use the Review and Formal Approval workflow."
    ),
    "follow_up_sql_forbidden": (
        "Follow-up chat cannot execute arbitrary SQL. "
        "Use the Review and Formal Approval workflow."
    ),
    "follow_up_external_url_forbidden": (
        "Follow-up chat cannot request arbitrary external URLs. "
        "Use the Review and Formal Approval workflow."
    ),
}


def detect_prohibited_follow_up(question: str) -> dict[str, Any] | None:
    """Return prohibition details when the question attempts a blocked action."""
    text = (question or "").strip().lower()
    if not text:
        return None
    for error_code, patterns in _PROHIBITION_RULES:
        if any(re.search(p, text, flags=re.IGNORECASE) for p in patterns):
            message = _MESSAGES[error_code]
            return {
                "error_code": error_code,
                "message": message,
                "unresolved": [message],
                "question_type": "prohibited_action",
                "suggested_next_action": FOLLOW_UP_PROHIBITED_NEXT_ACTION,
                "can_change_business_state": False,
            }
    return None


def _input_text(agent_input: Any) -> str:
    if isinstance(agent_input, str):
        return agent_input
    if isinstance(agent_input, list):
        parts: list[str] = []
        for item in agent_input:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(agent_input)


@input_guardrail(name="follow_up_prohibited_actions", run_in_parallel=False)
def follow_up_input_guardrail(
    ctx: RunContextWrapper[Any],
    agent: Agent[Any],
    agent_input: str | list[Any],
) -> GuardrailFunctionOutput:
    """SDK input guardrail — halt follow-up runs that attempt prohibited actions."""
    del ctx, agent  # unused; signature required by SDK
    hit = detect_prohibited_follow_up(_input_text(agent_input))
    if hit is None:
        return GuardrailFunctionOutput(output_info={"allowed": True}, tripwire_triggered=False)
    return GuardrailFunctionOutput(output_info=hit, tripwire_triggered=True)


@tool_input_guardrail(name="scenario_tool_input_guardrail")
def scenario_tool_input_guardrail(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Validate scenario tool inputs; reject invalid/unsafe arguments safely."""
    try:
        args = json.loads(data.context.tool_arguments or "{}")
    except json.JSONDecodeError:
        return ToolGuardrailFunctionOutput.reject_content(
            "Scenario tool arguments must be valid JSON."
        )
    if not isinstance(args, dict):
        return ToolGuardrailFunctionOutput.reject_content(
            "Scenario tool arguments must be a JSON object."
        )

    recommendation_id = str(args.get("recommendation_id") or "").strip()
    if not recommendation_id:
        return ToolGuardrailFunctionOutput.reject_content(
            "recommendation_id is required for scenario tools."
        )

    tool_name = data.context.tool_name
    if tool_name == "evaluate_quantity_scenario":
        qty = args.get("proposed_quantity")
        if isinstance(qty, bool) or not isinstance(qty, int):
            return ToolGuardrailFunctionOutput.reject_content(
                "proposed_quantity must be a whole number."
            )
        if qty < 0:
            return ToolGuardrailFunctionOutput.reject_content(
                "proposed_quantity must be zero or greater."
            )
        if qty > 1_000_000:
            return ToolGuardrailFunctionOutput.reject_content(
                "proposed_quantity exceeds the allowed scenario maximum."
            )
    elif tool_name == "evaluate_delay_scenario":
        days = args.get("delay_days")
        if isinstance(days, bool) or not isinstance(days, int):
            return ToolGuardrailFunctionOutput.reject_content(
                "delay_days must be an integer."
            )
        if days < 0:
            return ToolGuardrailFunctionOutput.reject_content(
                "delay_days must be zero or greater."
            )
        if days > 365:
            return ToolGuardrailFunctionOutput.reject_content(
                "delay_days exceeds the allowed scenario maximum."
            )

    return ToolGuardrailFunctionOutput.allow(
        output_info={"tool": tool_name, "recommendation_id": recommendation_id}
    )


FOLLOW_UP_INPUT_GUARDRAILS = [follow_up_input_guardrail]
SCENARIO_TOOL_INPUT_GUARDRAILS = [scenario_tool_input_guardrail]

"""PromptRenderer — sole owner of prompt assembly."""

from __future__ import annotations

import json
from typing import Any

from llm.contracts import ConversationContext, LLMRequest, PromptProvider, RenderedPrompt
from llm.prompts.provider import CatalogPromptProvider
from memory.rag.sanitize import format_retrieved_knowledge_block


def _render_body(template_body: str, values: dict[str, str]) -> str:
    out = template_body
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def _json_block(payload: Any) -> str:
    return json.dumps(payload if payload is not None else {}, default=str, sort_keys=True)


class PromptRenderer:
    """Assembles system/developer/user/memory/business/tool/conversation/knowledge prompts."""

    def __init__(self, prompt_provider: PromptProvider | None = None) -> None:
        self._prompts = prompt_provider or CatalogPromptProvider()

    def render(
        self,
        request: LLMRequest,
        *,
        memory_context: dict[str, Any] | None = None,
    ) -> RenderedPrompt:
        memory_payload = memory_context or {}
        conversation_text = self._format_conversation(request.conversation)
        # Knowledge is untrusted — never merged into system/developer templates.
        knowledge_items = list(memory_payload.get("retrieved_knowledge") or [])
        retrieved_block = format_retrieved_knowledge_block(knowledge_items)

        # Structured memory only in memory_context (exclude retrieved_knowledge blob duplication).
        structured_memory = {
            k: v
            for k, v in memory_payload.items()
            if k not in {"retrieved_knowledge"}
        }

        values = {
            "workflow": request.workflow or "unknown",
            "user_input": request.user_input or "",
            "allowed_tools": ", ".join(request.allowed_tools) or "(none)",
            "memory_context": _json_block(structured_memory),
            "store_id": request.store_id or "",
            "sku": request.sku or "",
            "recommendation_id": request.recommendation_id or "",
            "approval_id": request.approval_id or "",
            "supplier_id": request.supplier_id or "",
            "purchase_order_id": request.purchase_order_id or "",
            "business_context": _json_block(request.business_context),
            "tool_context": _json_block(request.tool_context),
            "conversation_context": conversation_text or "(empty)",
            "retrieved_knowledge": retrieved_block,
        }

        # System/developer first; knowledge is appended as a separate user-role block
        # so document text cannot act as system instructions.
        order = [
            ("system.default", "system"),
            ("developer.default", "system"),
            ("memory.context", "system"),
            ("business.context", "system"),
            ("tool.context", "system"),
            ("conversation.context", "system"),
            ("retrieved.knowledge", "user"),
            ("user.default", "user"),
        ]
        messages: list[dict[str, str]] = []
        template_ids: list[str] = []
        for template_id, api_role in order:
            template = self._prompts.get_template(template_id)
            if template_id == "memory.context" and not structured_memory:
                continue
            if template_id == "tool.context" and not request.tool_context:
                continue
            if template_id == "conversation.context" and not conversation_text:
                continue
            if template_id == "retrieved.knowledge" and not knowledge_items:
                continue
            body = _render_body(template.body, values)
            messages.append({"role": api_role, "content": body})
            template_ids.append(template_id)

        encoded = json.dumps(messages, default=str)
        context_encoded = json.dumps(
            {
                "memory": structured_memory,
                "business": request.business_context,
                "tools": request.tool_context,
                "retrieved_knowledge_count": len(knowledge_items),
            },
            default=str,
        )
        sources = list(memory_payload.get("knowledge_sources") or [])
        sources.extend(
            [
                str(item.get("citation") or item.get("source_reference") or "")
                for item in knowledge_items
            ]
        )
        return RenderedPrompt(
            messages=messages,
            prompt_size_chars=len(encoded),
            context_size_chars=len(context_encoded),
            template_ids=template_ids,
            knowledge_sources=sorted({s for s in sources if s}),
        )

    @staticmethod
    def _format_conversation(conversation: ConversationContext | None) -> str:
        if conversation is None or not conversation.messages:
            return ""
        lines = []
        for msg in conversation.messages:
            prefix = msg.name or msg.role
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

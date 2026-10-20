"""Prompt provider — template catalog only (no assembly)."""

from __future__ import annotations

from llm.contracts import PromptProvider, PromptTemplate
from llm.prompts.templates import DEFAULT_TEMPLATES


class CatalogPromptProvider:
    """In-process prompt catalog. Business services must not construct prompts."""

    def __init__(self, templates: dict[str, PromptTemplate] | None = None) -> None:
        self._templates = dict(templates or DEFAULT_TEMPLATES)

    def get_template(self, template_id: str) -> PromptTemplate:
        if template_id not in self._templates:
            raise KeyError(f"Unknown prompt template: {template_id}")
        return self._templates[template_id]

    def list_templates(self) -> list[PromptTemplate]:
        return list(self._templates.values())


# Protocol marker for importers
_ = PromptProvider

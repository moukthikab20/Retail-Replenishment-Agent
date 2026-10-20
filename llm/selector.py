"""Model selection from configuration."""

from __future__ import annotations

from typing import Any

from config import LLM_MODEL, LLM_PROVIDER, OPENAI_MODEL


class ModelSelector:
    """Selects provider model string — no autonomous routing."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self.provider = (provider or LLM_PROVIDER or "mock").strip().lower()
        self.default_model = (
            default_model
            or LLM_MODEL
            or OPENAI_MODEL
            or ("mock-replenishment-v1" if self.provider == "mock" else "gpt-4o-mini")
        )

    def select(self, *, requested_model: str | None = None, workflow: str | None = None) -> str:
        if requested_model:
            return requested_model
        # Workflow hint only adjusts mock label — no multi-agent routing.
        if self.provider == "mock" and workflow:
            return f"mock-{workflow}-v1"
        return self.default_model

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "default_model": self.default_model,
        }

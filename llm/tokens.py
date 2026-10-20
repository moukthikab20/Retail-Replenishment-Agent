"""Token estimation (heuristic — no embedding model required)."""

from __future__ import annotations

from llm.contracts import RenderedPrompt


class TokenEstimator:
    """Rough character-based token estimator (≈4 chars/token)."""

    def __init__(self, *, chars_per_token: float = 4.0) -> None:
        self.chars_per_token = max(1.0, float(chars_per_token))

    def estimate_text(self, text: str) -> int:
        return max(0, int(round(len(text or "") / self.chars_per_token)))

    def estimate_prompt(self, rendered: RenderedPrompt) -> int:
        total = sum(len(m.get("content") or "") for m in rendered.messages)
        return self.estimate_text("x" * total)

    def estimate_messages(self, messages: list[dict[str, str]]) -> int:
        total = sum(len(m.get("content") or "") for m in messages)
        return self.estimate_text("x" * total)

    def would_exceed(self, estimated: int, max_tokens: int) -> bool:
        return estimated > max(1, int(max_tokens))

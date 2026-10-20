"""Embedding providers — mock + optional OpenAI."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from integrations.failures import ProviderConfigError, ProviderError, ProviderFailureCode


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$]+", (text or "").lower())


class MockEmbeddingProvider:
    """
    Deterministic bag-of-tokens embedding for tests / offline demos.
    Same text always yields the same vector.
    """

    provider_name = "mock"
    DIMENSIONS = 64

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.DIMENSIONS
        tokens = _tokenize(text)
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = digest[0] % self.DIMENSIONS
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            weight = 1.0 + (digest[2] / 255.0)
            vec[idx] += sign * weight
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_name,
            "dimensions": self.DIMENSIONS,
            "message": "Mock embedding provider ready.",
        }


class OpenAIEmbeddingProvider:
    """Optional OpenAI embeddings — disabled without API key."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
    ) -> None:
        from config import OPENAI_API_KEY

        self.api_key = (api_key if api_key is not None else OPENAI_API_KEY) or ""
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise ProviderError(
                code=ProviderFailureCode.CONFIG_ERROR.value,
                message="OpenAI embedding provider requires OPENAI_API_KEY.",
                provider=self.provider_name,
            )
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            response = client.embeddings.create(model=self.model, input=list(texts))
            # Preserve input order
            by_index = {item.index: item.embedding for item in response.data}
            return [list(by_index[i]) for i in range(len(texts))]
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                code=ProviderFailureCode.PROVIDER_UNAVAILABLE.value,
                message="OpenAI embedding request failed.",
                provider=self.provider_name,
                details={"error_type": type(exc).__name__},
            ) from exc

    def health_check(self) -> dict[str, Any]:
        configured = bool(self.api_key)
        return {
            "ok": configured,
            "provider": self.provider_name,
            "configured": configured,
            "model": self.model,
            "message": (
                "OpenAI embedding provider ready."
                if configured
                else "OpenAI embedding provider disabled — API key missing."
            ),
        }


_SUPPORTED = {
    "mock": MockEmbeddingProvider,
    "openai": OpenAIEmbeddingProvider,
}

_provider: Any = None


def validate_embedding_provider_configuration(key: str | None = None) -> str:
    from config import EMBEDDING_PROVIDER

    value = (key or EMBEDDING_PROVIDER or "mock").strip().lower()
    if value not in _SUPPORTED:
        available = ", ".join(sorted(_SUPPORTED))
        raise ProviderConfigError(
            f"Embedding provider '{value}' is not available. Supported: {available}.",
            provider_key="embedding",
        )
    return value


def get_embedding_provider(*, force_new: bool = False):
    global _provider
    key = validate_embedding_provider_configuration()
    if _provider is None or force_new:
        _provider = _SUPPORTED[key]()
    return _provider


def reset_embedding_provider() -> None:
    global _provider
    _provider = None

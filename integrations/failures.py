"""Normalized integration / provider failures."""

from __future__ import annotations

from dataclasses import dataclass
try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal StrEnum backport."""

from typing import Any


class ProviderFailureCode(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    RECORD_NOT_FOUND = "record_not_found"
    STALE_DATA = "stale_data"
    INVALID_RESPONSE = "invalid_response"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    CONFIG_ERROR = "config_error"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass
class ProviderError(Exception):
    """Structured provider failure — never expose raw client/HTTP details to UI."""

    code: str
    message: str
    provider: str | None = None
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        prefix = f"[{self.provider}] " if self.provider else ""
        return f"{prefix}{self.code}: {self.message}"


class ProviderConfigError(ProviderError):
    """Unknown or unsupported provider configuration."""

    def __init__(self, message: str, *, provider_key: str | None = None) -> None:
        super().__init__(
            code=ProviderFailureCode.CONFIG_ERROR.value,
            message=message,
            provider=provider_key,
        )

"""Authentication provider contracts."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from models.identity import AuthenticatedIdentity


@runtime_checkable
class AuthenticationProvider(Protocol):
    provider_name: str

    def authenticate(self, *, access_code: str | None, user_id: str | None, **kwargs: Any) -> AuthenticatedIdentity:
        """Authenticate and return identity (session not yet issued)."""
        ...

    def supports_demo_access_code(self) -> bool:
        ...

    def health_check(self) -> dict[str, Any]:
        ...

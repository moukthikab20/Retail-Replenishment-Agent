"""Authentication provider factory."""

from __future__ import annotations

from typing import Any

from config import AUTH_PROVIDER
from integrations.auth.contracts import AuthenticationProvider
from integrations.auth.demo_provider import DemoAuthenticationProvider
from integrations.failures import ProviderConfigError

_SUPPORTED: dict[str, type] = {
    "demo": DemoAuthenticationProvider,
}

_provider: AuthenticationProvider | None = None


def validate_auth_provider_configuration() -> str:
    key = (AUTH_PROVIDER or "demo").strip().lower()
    if key not in _SUPPORTED:
        available = ", ".join(sorted(_SUPPORTED))
        raise ProviderConfigError(
            f"Authentication provider '{key}' is not available in this deployment. "
            f"Supported: {available}. OIDC/Entra/Okta are not implemented yet.",
            provider_key="auth",
        )
    return key


def get_authentication_provider(*, force_new: bool = False) -> AuthenticationProvider:
    global _provider
    key = validate_auth_provider_configuration()
    if _provider is None or force_new:
        _provider = _SUPPORTED[key]()
    return _provider


def reset_authentication_provider() -> None:
    global _provider
    _provider = None


def auth_provider_health() -> dict[str, Any]:
    provider = get_authentication_provider()
    payload = provider.health_check()
    payload.setdefault("config", (AUTH_PROVIDER or "demo").strip().lower())
    return payload

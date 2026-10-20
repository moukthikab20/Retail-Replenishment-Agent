"""Authentication façade + deterministic authorization (outside the model).

Demo login uses AuthenticationProvider + signed application sessions.
UI must not be the only authorization boundary — services call require_*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import APP_ENV, AUTH_PROVIDER, DEMO_USERS, ROLE_HIERARCHY
from integrations.auth.demo_provider import DemoAuthError
from integrations.auth.factory import (
    auth_provider_health,
    get_authentication_provider,
    reset_authentication_provider,
    validate_auth_provider_configuration,
)
from integrations.auth.permissions import (
    EDIT_POLICY,
    FORMAL_APPROVAL,
    MANUAL_QUANTITY_BLOCKED,
    RECALL_AUTO_RELEASE,
    RESET_DEMO_DATA,
    RETRY_BLOCKED,
    REVIEW_RECOMMENDATION,
    RUN_ANALYSIS,
    TRIGGER_MANUAL_BATCH,
    VIEW_ADMINISTRATION,
    VIEW_AGENT_OPERATIONS,
    permissions_for_roles,
)
from integrations.auth.session_store import (
    SessionError,
    get_session_store,
    reset_session_store,
)
from integrations.failures import ProviderConfigError
from models.identity import AuthenticatedIdentity


class AuthError(PermissionError):
    """Raised when authentication or authorization fails."""


@dataclass(frozen=True)
class DemoUser:
    user_id: str
    display_name: str
    role: str

    def to_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "role": self.role,
        }


def list_demo_users() -> list[DemoUser]:
    return [
        DemoUser(
            user_id=user_id,
            display_name=meta["display_name"],
            role=meta["role"],
        )
        for user_id, meta in DEMO_USERS.items()
    ]


def get_demo_user(user_id: str) -> DemoUser:
    meta = DEMO_USERS.get(user_id)
    if meta is None:
        raise AuthError(f"Unknown demo user: {user_id}")
    return DemoUser(user_id=user_id, display_name=meta["display_name"], role=meta["role"])


def expected_access_code() -> str:
    """
    Legacy server-side demo access code helper.

    Demo workspace entry no longer requires an access code. Kept for
    compatibility with older admin/health callers.
    """
    if (AUTH_PROVIDER or "demo").strip().lower() != "demo":
        raise AuthError("Demo access codes are not used for this authentication provider")
    provider = get_authentication_provider()
    try:
        return provider.expected_access_code()  # type: ignore[attr-defined]
    except DemoAuthError as exc:
        raise AuthError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Demo access codes are not used for this authentication provider") from exc


def verify_access_code(provided: str) -> bool:
    """Legacy helper — always False for UI gating; access codes are not required."""
    _ = provided
    return False


def login(*, access_code: str | None = None, user_id: str | None = None) -> tuple[str, AuthenticatedIdentity]:
    """Authenticate via configured provider and issue a signed application session."""
    try:
        validate_auth_provider_configuration()
        provider = get_authentication_provider()
        if (AUTH_PROVIDER or "demo").strip().lower() != "demo":
            # Future providers must not accept DEMO_ACCESS_CODE.
            if access_code:
                raise AuthError("Demo access codes cannot authenticate this provider")
        identity = provider.authenticate(access_code=access_code, user_id=user_id)
    except ProviderConfigError as exc:
        raise AuthError(str(exc)) from exc
    except DemoAuthError as exc:
        raise AuthError(str(exc)) from exc
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AuthError("Authentication failed. Please select a user again.") from exc

    token, record = get_session_store().create(identity)
    return token, record.identity


def select_demo_user(user_id: str) -> dict[str, Any]:
    """Open a demo workspace for the selected persona (no access code)."""
    return authenticate(user_id=user_id)


def authenticate(access_code: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Issue a signed session for a demo user. Access codes are ignored."""
    if not user_id:
        raise AuthError("User is required")
    token, identity = login(access_code=access_code, user_id=user_id)
    payload = identity.to_legacy_user_dict()
    payload["session_token"] = token
    payload["authenticated"] = "true"
    return payload


def logout(session_token: str | None = None, session_id: str | None = None) -> None:
    store = get_session_store()
    if session_token:
        store.revoke_token(session_token)
    elif session_id:
        store.revoke(session_id)


def validate_session(session_token: str | None) -> AuthenticatedIdentity:
    try:
        return get_session_store().validate_token(session_token)
    except SessionError as exc:
        raise AuthError(str(exc)) from exc


def identity_from_role(
    *,
    user_id: str,
    display_name: str | None,
    role: str,
    session_id: str | None = None,
    authentication_source: str = "legacy",
) -> AuthenticatedIdentity:
    """Build identity for service tests / system paths that already know the role."""
    from datetime import datetime, timezone

    roles = (role,)
    return AuthenticatedIdentity(
        user_id=user_id,
        display_name=display_name or user_id,
        email=None,
        roles=roles,
        permissions=permissions_for_roles(roles),
        authentication_source=authentication_source,
        authenticated_at=datetime.now(timezone.utc),
        session_id=session_id or "SESS-legacy",
    )


def role_rank(role: str) -> int:
    return ROLE_HIERARCHY.get(role, 0)


def role_satisfies(actor_role: str, required_role: str) -> bool:
    return role_rank(actor_role) >= role_rank(required_role)


def can_view(role: str) -> bool:
    return role_rank(role) >= role_rank("viewer")


def can_run_analysis(role: str) -> bool:
    return role_rank(role) >= role_rank("store_manager")


def can_submit_human_review(role: str) -> bool:
    return role_rank(role) >= role_rank("store_manager")


def can_request_approval(role: str) -> bool:
    return can_submit_human_review(role)


def can_approve(role: str, required_role: str) -> bool:
    if role_rank(role) < role_rank("store_manager"):
        return False
    return role_satisfies(role, required_role)


def can_create_purchase_order(role: str) -> bool:
    return role_rank(role) >= role_rank("store_manager")


def can_reset_demo(role: str) -> bool:
    return role == "administrator"


def can_trigger_batch_run(role: str) -> bool:
    return role == "administrator"


def can_edit_policy(role: str) -> bool:
    return role == "administrator"


def can_recall_auto_release(role: str) -> bool:
    return role_rank(role) >= role_rank("category_manager")


def can_manual_quantity_blocked(role: str) -> bool:
    return role_rank(role) >= role_rank("inventory_planner")


def can_retry_blocked(role: str) -> bool:
    return role_rank(role) >= role_rank("store_manager")


def can_view_agent_operations(role: str) -> bool:
    return role == "administrator"


def can_view_administration(role: str) -> bool:
    return role == "administrator"


def require_permission(role: str, allowed: bool, action: str) -> None:
    if not allowed:
        raise AuthError(f"You do not have permission to {action}.")


def require_role(role: str | None, action: str) -> str:
    if not role:
        raise AuthError(f"You do not have permission to {action}.")
    return role


def authorize_approval(actor_role: str, required_role: str) -> None:
    require_permission(
        actor_role,
        can_approve(actor_role, required_role),
        "approve this recommendation",
    )


def authorize_hitl_resume(actor_role: str | None, required_role: str | None) -> None:
    role = require_role(actor_role, "resume this waiting execution")
    needed = required_role or "store_manager"
    authorize_approval(role, needed)


def authorize_run_analysis(actor_role: str | None) -> None:
    role = require_role(actor_role, "run analysis")
    require_permission(role, can_run_analysis(role), "run analysis")


def authorize_agent_operations(actor_role: str | None) -> None:
    role = require_role(actor_role, "view Agent Operations")
    require_permission(
        role,
        can_view_agent_operations(role),
        "view Agent Operations",
    )


def authorize_administration(actor_role: str | None) -> None:
    role = require_role(actor_role, "access Administration")
    require_permission(
        role,
        can_view_administration(role) or can_trigger_batch_run(role),
        "access Administration",
    )


def audit_actor_fields(identity: AuthenticatedIdentity | None = None, **overrides: Any) -> dict[str, Any]:
    """Fields suitable for append-only audit writes."""
    if identity is None:
        return {
            "actor": overrides.get("actor", "system"),
            "actor_role": overrides.get("actor_role"),
            "user_id": overrides.get("user_id"),
            "session_id": overrides.get("session_id"),
            "authentication_source": overrides.get("authentication_source", "system"),
        }
    return {
        "actor": identity.user_id,
        "actor_role": identity.role,
        "user_id": identity.user_id,
        "session_id": identity.session_id,
        "authentication_source": identity.authentication_source,
        "display_name": identity.display_name,
    }


def public_auth_config() -> dict[str, Any]:
    """Non-secret config safe to show in the UI."""
    provider_key = (AUTH_PROVIDER or "demo").strip().lower()
    demo_mode = provider_key == "demo"
    return {
        "app_env": APP_ENV,
        "auth_provider": provider_key,
        "demo_mode": demo_mode,
        "access_code_configured": False,
        "session_ttl_minutes": int(__import__("config", fromlist=["SESSION_TTL_MINUTES"]).SESSION_TTL_MINUTES),
        "demo_users": [
            {"user_id": u.user_id, "display_name": u.display_name, "role": u.role}
            for u in list_demo_users()
        ]
        if demo_mode
        else [],
        "oidc_configured": False,
    }


def authentication_health() -> dict[str, Any]:
    try:
        validate_auth_provider_configuration()
        provider = auth_provider_health()
        sessions = get_session_store().health()
        return {
            "ok": bool(provider.get("ok")),
            "status": provider.get("status") or ("healthy" if provider.get("ok") else "unavailable"),
            "provider_name": provider.get("provider_name") or AUTH_PROVIDER,
            "source": provider.get("source") or AUTH_PROVIDER,
            "message": provider.get("message") or "",
            "sessions": sessions,
            "config": (AUTH_PROVIDER or "demo").strip().lower(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": "unavailable",
            "provider_name": AUTH_PROVIDER,
            "source": AUTH_PROVIDER,
            "message": "Authentication provider unavailable.",
            "error_type": type(exc).__name__,
        }


def reset_auth_state() -> None:
    """Test helper."""
    reset_session_store()
    reset_authentication_provider()

"""Demo authentication and deterministic authorization (outside the model)."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from config import APP_ENV, DEMO_ACCESS_CODE, DEMO_USERS, ROLE_HIERARCHY


class AuthError(PermissionError):
    """Raised when demo authentication or authorization fails."""


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
    Server-side access code.

    Never return this value to the Streamlit browser UI.
    In development, fall back to a well-known local code when unset.
    """
    if DEMO_ACCESS_CODE:
        return DEMO_ACCESS_CODE
    if APP_ENV in {"development", "test", "local"}:
        return "infolob-demo"
    raise AuthError("DEMO_ACCESS_CODE is not configured for this environment")


def verify_access_code(provided: str) -> bool:
    expected = expected_access_code()
    return hmac.compare_digest((provided or "").strip(), expected)


def authenticate(access_code: str, user_id: str) -> dict[str, str]:
    """Validate access code + named demo user. Returns session identity payload."""
    if not verify_access_code(access_code):
        raise AuthError("Invalid access code")
    user = get_demo_user(user_id)
    return {
        **user.to_dict(),
        "session_id": f"SESS-{uuid4().hex[:16]}",
        "authenticated": "true",
    }


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


def require_permission(role: str, allowed: bool, action: str) -> None:
    if not allowed:
        raise AuthError(f"Role '{role}' is not authorized to {action}")


def authorize_approval(actor_role: str, required_role: str) -> None:
    require_permission(
        actor_role,
        can_approve(actor_role, required_role),
        f"approve (requires {required_role})",
    )


def public_auth_config() -> dict[str, Any]:
    """Non-secret config safe to show in the UI."""
    return {
        "app_env": APP_ENV,
        "access_code_configured": bool(DEMO_ACCESS_CODE) or APP_ENV in {"development", "test", "local"},
        "demo_users": [
            {"user_id": u.user_id, "display_name": u.display_name, "role": u.role}
            for u in list_demo_users()
        ],
    }

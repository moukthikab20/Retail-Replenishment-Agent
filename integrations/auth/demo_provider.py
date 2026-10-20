"""Demo authentication provider — named DEMO_USERS workspace selection."""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from config import APP_ENV, DEMO_ACCESS_CODE, DEMO_USERS
from integrations.auth.permissions import permissions_for_roles
from models.identity import AuthenticatedIdentity


class DemoAuthError(PermissionError):
    pass


class DemoAuthenticationProvider:
    provider_name = "demo"

    def supports_demo_access_code(self) -> bool:
        # Access codes are no longer required to enter the demo workspace.
        return False

    def expected_access_code(self) -> str:
        if DEMO_ACCESS_CODE:
            return DEMO_ACCESS_CODE
        if APP_ENV in {"development", "test", "local"}:
            return "infolob-demo"
        raise DemoAuthError("DEMO_ACCESS_CODE is not configured for this environment")

    def verify_access_code(self, provided: str) -> bool:
        """Legacy helper — demo entry no longer gates on access codes."""
        try:
            expected = self.expected_access_code()
        except DemoAuthError:
            return False
        return hmac.compare_digest((provided or "").strip(), expected)

    def authenticate(
        self,
        *,
        access_code: str | None = None,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> AuthenticatedIdentity:
        _ = access_code  # Intentionally unused — user selection alone opens the workspace.
        if not user_id:
            raise DemoAuthError("User is required")
        meta = DEMO_USERS.get(user_id)
        if meta is None:
            raise DemoAuthError("Unknown demo user")
        role = str(meta["role"])
        roles = (role,)
        return AuthenticatedIdentity(
            user_id=user_id,
            display_name=str(meta["display_name"]),
            email=None,
            roles=roles,
            permissions=permissions_for_roles(roles),
            authentication_source="demo",
            authenticated_at=datetime.now(timezone.utc),
            session_id=f"SESS-{uuid4().hex[:16]}",
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "healthy",
            "provider_name": self.provider_name,
            "source": "Demo",
            "message": "Demo workspace selection ready.",
            "demo_users": len(DEMO_USERS),
            "access_code_configured": False,
        }

"""Typed authenticated identity and session records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuthenticatedIdentity:
    user_id: str
    display_name: str
    email: str | None
    roles: tuple[str, ...]
    permissions: frozenset[str]
    authentication_source: str
    authenticated_at: datetime
    session_id: str
    directory_id: str | None = None
    tenant_id: str | None = None

    @property
    def role(self) -> str:
        """Primary role for hierarchy checks (highest rank if multiple)."""
        if not self.roles:
            return "viewer"
        from config import ROLE_HIERARCHY

        return max(self.roles, key=lambda r: ROLE_HIERARCHY.get(r, 0))

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["roles"] = list(self.roles)
        payload["permissions"] = sorted(self.permissions)
        payload["authenticated_at"] = self.authenticated_at.isoformat()
        payload["role"] = self.role  # legacy single-role field
        return payload

    def to_legacy_user_dict(self) -> dict[str, Any]:
        """Streamlit / page-compatible shape used across existing UI."""
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "role": self.role,
            "session_id": self.session_id,
            "email": self.email,
            "authentication_source": self.authentication_source,
            "permissions": sorted(self.permissions),
            "authenticated": True,
        }


@dataclass
class AppSession:
    session_id: str
    identity: AuthenticatedIdentity
    created_at: datetime
    expires_at: datetime
    revoked: bool = False
    signature: str = ""

    def is_active(self, *, now: datetime | None = None) -> bool:
        from datetime import timezone

        clock = now or datetime.now(timezone.utc)
        if self.revoked:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=timezone.utc)
        return clock <= expires

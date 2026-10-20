"""In-process signed application session store."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from config import SESSION_SECRET, SESSION_TTL_MINUTES
from models.identity import AppSession, AuthenticatedIdentity


class SessionError(PermissionError):
    """Session missing, expired, or invalid."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sign(session_id: str) -> str:
    secret = (SESSION_SECRET or "dev-only-session-secret").encode("utf-8")
    return hmac.new(secret, session_id.encode("utf-8"), hashlib.sha256).hexdigest()


class ApplicationSessionStore:
    """Server-side session registry. Streamlit only holds the opaque token."""

    def __init__(self) -> None:
        self._sessions: dict[str, AppSession] = {}

    def create(self, identity: AuthenticatedIdentity, *, ttl_minutes: int | None = None) -> tuple[str, AppSession]:
        ttl = ttl_minutes if ttl_minutes is not None else SESSION_TTL_MINUTES
        session_id = identity.session_id or f"SESS-{secrets.token_hex(8)}"
        signature = _sign(session_id)
        now = _now()
        bound = AuthenticatedIdentity(
            user_id=identity.user_id,
            display_name=identity.display_name,
            email=identity.email,
            roles=identity.roles,
            permissions=identity.permissions,
            authentication_source=identity.authentication_source,
            authenticated_at=identity.authenticated_at,
            session_id=session_id,
            directory_id=identity.directory_id,
            tenant_id=identity.tenant_id,
        )
        record = AppSession(
            session_id=session_id,
            identity=bound,
            created_at=now,
            expires_at=now + timedelta(minutes=max(1, int(ttl))),
            revoked=False,
            signature=signature,
        )
        self._sessions[session_id] = record
        token = f"{session_id}.{signature}"
        return token, record

    def validate_token(self, token: str | None) -> AuthenticatedIdentity:
        if not token or "." not in token:
            raise SessionError("Your session has expired. Please sign in again.")
        session_id, signature = token.rsplit(".", 1)
        expected = _sign(session_id)
        if not hmac.compare_digest(signature, expected):
            raise SessionError("Your session has expired. Please sign in again.")
        record = self._sessions.get(session_id)
        if record is None or not record.is_active():
            raise SessionError("Your session has expired. Please sign in again.")
        if not hmac.compare_digest(record.signature, signature):
            raise SessionError("Your session has expired. Please sign in again.")
        return record.identity

    def revoke(self, session_id: str | None) -> None:
        if not session_id:
            return
        record = self._sessions.get(session_id)
        if record is not None:
            record.revoked = True

    def revoke_token(self, token: str | None) -> None:
        if not token or "." not in token:
            return
        session_id, _ = token.rsplit(".", 1)
        self.revoke(session_id)

    def clear(self) -> None:
        self._sessions.clear()

    def health(self) -> dict[str, Any]:
        active = sum(1 for s in self._sessions.values() if s.is_active())
        return {
            "ok": True,
            "active_sessions": active,
            "ttl_minutes": SESSION_TTL_MINUTES,
        }


_STORE = ApplicationSessionStore()


def get_session_store() -> ApplicationSessionStore:
    return _STORE


def reset_session_store() -> None:
    _STORE.clear()

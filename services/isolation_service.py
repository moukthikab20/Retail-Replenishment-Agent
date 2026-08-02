"""Multi-user visibility rules for workflow records."""

from __future__ import annotations

from typing import Any

from services import auth_service
from services.errors import AppError


def can_access_recommendation(
    record: dict[str, Any],
    *,
    user_id: str | None,
    role: str | None,
) -> bool:
    """
    Owners always access their records.
    Approver roles and administrators may access records for review/approval.
    Viewers only access their own records (typically none).
    """
    if role == "administrator":
        return True
    owner = record.get("user_id")
    if user_id and owner and owner == user_id:
        return True
    if role and auth_service.can_submit_human_review(role):
        # Store managers and above can open pending workflow items in the shared demo
        return True
    return False


def require_recommendation_access(
    record: dict[str, Any],
    *,
    user_id: str | None,
    role: str | None,
) -> None:
    if not can_access_recommendation(record, user_id=user_id, role=role):
        raise AppError("You do not have access to this recommendation.", code="forbidden")

"""Production-safe exception helpers — never leak secrets to the UI."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from services.auth_service import AuthError

logger = logging.getLogger(__name__)


class AppError(Exception):
    """User-safe application error."""

    def __init__(self, message: str, *, code: str = "app_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class RateLimitError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="rate_limit")


class IdempotencyConflictError(AppError):
    def __init__(self, message: str = "This action was already processed.") -> None:
        super().__init__(message, code="already_processed")


def user_facing_error(exc: BaseException) -> str:
    """Map exceptions to short, non-sensitive messages for Streamlit."""
    if isinstance(exc, (AppError, AuthError, RateLimitError, IdempotencyConflictError)):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "You are not authorized to perform this action."
    if isinstance(exc, IntegrityError):
        return "This action was already processed. Refresh to see the latest status."
    if isinstance(exc, ValueError):
        text = str(exc)
        if any(token in text.lower() for token in ("api_key", "password", "secret", "token")):
            return "A configuration error occurred. Contact the demo host."
        return text
    if isinstance(exc, SQLAlchemyError):
        logger.exception("Database error")
        return "A database error occurred. Please try again shortly."
    logger.exception("Unexpected application error")
    return "Something went wrong. Please try again."


def sanitize_public_dict(data: dict[str, Any]) -> dict[str, Any]:
    blocked = {"api_key", "openai_api_key", "authorization", "password", "secret", "token", "state_json"}
    return {k: v for k, v in data.items() if k.lower() not in blocked and "api_key" not in k.lower()}

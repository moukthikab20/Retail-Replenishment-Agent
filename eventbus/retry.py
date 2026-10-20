"""Retry policy for transient handler failures."""

from __future__ import annotations

from enum import StrEnum


class RetryMode(StrEnum):
    NONE = "none"
    FIXED = "fixed"
    EXPONENTIAL = "exponential"


class EventRetryPolicy:
    def __init__(
        self,
        *,
        mode: str = RetryMode.EXPONENTIAL,
        max_attempts: int = 3,
        delay_seconds: float = 0.01,
        backoff_multiplier: float = 2.0,
    ) -> None:
        self.mode = mode
        self.max_attempts = max(1, int(max_attempts))
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.backoff_multiplier = max(1.0, float(backoff_multiplier))

    def should_retry(self, attempt: int, *, retryable: bool = True) -> bool:
        if not retryable or self.mode == RetryMode.NONE:
            return False
        return attempt < self.max_attempts

    def delay_for(self, attempt: int) -> float:
        if self.mode == RetryMode.EXPONENTIAL:
            return self.delay_seconds * (self.backoff_multiplier ** max(0, attempt - 1))
        return self.delay_seconds

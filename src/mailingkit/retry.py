"""Short, in-call retries for transient provider failures.

These retries smooth over a dropped connection or a brief rate limit while the caller waits.
Long-lived, durable retries belong to a queue, not here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from mailingkit.errors import ProviderError, RateLimitError

__all__ = ["NO_RETRY", "RetryPolicy"]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with full jitter. Only errors with ``retryable=True`` are retried."""

    max_attempts: int = 3
    initial_delay: float = 0.5
    max_delay: float = 10.0
    multiplier: float = 2.0
    jitter: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay < 0 or self.max_delay < 0:
            raise ValueError("Retry delays cannot be negative")

    def should_retry(self, attempt: int, error: ProviderError) -> bool:
        return error.retryable and attempt < self.max_attempts

    def delay(self, attempt: int, error: ProviderError | None = None) -> float:
        """Seconds to wait after the given (1-based) failed attempt."""
        if isinstance(error, RateLimitError) and error.retry_after is not None:
            return min(max(error.retry_after, 0.0), self.max_delay)
        base = min(self.max_delay, self.initial_delay * self.multiplier ** (attempt - 1))
        return random.uniform(0, base) if self.jitter else base  # noqa: S311 (not crypto)


NO_RETRY = RetryPolicy(max_attempts=1)

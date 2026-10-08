"""What a send returns, and the events MailingKit emits along the way."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, TypeAlias

__all__ = ["EventName", "Hook", "MailEvent", "ProviderResponse", "SendResult"]


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """What a provider returns after accepting a message."""

    provider_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class SendResult:
    """The outcome of a successful send.

    ``id`` is MailingKit's own identifier for the send. ``provider_message_id`` is the
    provider's identifier, useful when matching delivery webhooks or support tickets later.
    ``duplicate`` is true when an earlier send with the same idempotency key was reused.
    """

    id: str
    provider: str
    provider_message_id: str | None
    attempts: int
    idempotency_key: str | None = None
    duplicate: bool = False
    redirected: bool = False
    accepted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


EventName: TypeAlias = Literal["mail.sent", "mail.failed", "mail.retry", "mail.duplicate"]


@dataclass(frozen=True, slots=True)
class MailEvent:
    """Passed to hooks. Holds no recipients, bodies or template data, so it is safe to log."""

    name: EventName
    id: str
    provider: str
    attempt: int
    template: str | None = None
    recipient_count: int = 0
    error: Exception | None = None
    result: SendResult | None = None


Hook: TypeAlias = Callable[[MailEvent], Awaitable[None] | None]

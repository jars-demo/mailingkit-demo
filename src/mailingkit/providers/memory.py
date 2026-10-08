"""Keeps sent messages in a list. Built for tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Self

from mailingkit.errors import ProviderError
from mailingkit.message import EmailMessage
from mailingkit.providers.base import EmailProvider
from mailingkit.results import ProviderResponse

__all__ = ["MemoryProvider"]


class MemoryProvider(EmailProvider):
    """Stores every message in :attr:`outbox` instead of sending it.

    ::

        provider = MemoryProvider()
        mail = MailingKit(provider, default_sender="app@example.com")
        await mail.send(to="ada@example.com", subject="Hi", text="Hello")
        assert provider.last.subject == "Hi"

    :meth:`fail_next` queues errors to raise, which is how retry behaviour is tested.
    """

    name = "memory"

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []
        self.idempotency_keys: list[str | None] = []
        self._failures: deque[ProviderError] = deque()

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        return cls()

    async def send(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> ProviderResponse:
        if self._failures:
            raise self._failures.popleft()
        self.outbox.append(message)
        self.idempotency_keys.append(idempotency_key)
        return ProviderResponse(provider_message_id=f"memory-{len(self.outbox)}")

    def fail_next(self, *errors: ProviderError) -> None:
        """Raise these errors, in order, on the next sends."""
        self._failures.extend(errors)

    def clear(self) -> None:
        self.outbox.clear()
        self.idempotency_keys.clear()
        self._failures.clear()

    @property
    def last(self) -> EmailMessage:
        if not self.outbox:
            raise LookupError("No messages have been sent")
        return self.outbox[-1]

    def sent_to(self, email: str) -> list[EmailMessage]:
        """Messages where ``email`` is among the recipients (to, cc or bcc)."""
        wanted = email.lower()
        return [m for m in self.outbox if any(a.email.lower() == wanted for a in m.recipients)]

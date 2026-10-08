"""The contract every provider adapter implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar, Self

from mailingkit.errors import ConfigurationError
from mailingkit.message import EmailMessage
from mailingkit.results import ProviderResponse

__all__ = ["EmailProvider"]


class EmailProvider(ABC):
    """Base class for provider adapters.

    A provider receives a message that is already rendered, validated and addressed. Its only
    jobs are to hand that message to the service and to translate failures into the
    :mod:`mailingkit.errors` provider exceptions, setting ``retryable`` honestly.

    Minimal custom provider::

        class MyProvider(EmailProvider):
            name = "my-provider"

            async def send(self, message, *, idempotency_key=None):
                provider_id = await my_api.post(...)
                return ProviderResponse(provider_message_id=provider_id)
    """

    #: Short name used in results, events and ``MAILINGKIT_PROVIDER``.
    name: ClassVar[str] = "custom"
    #: True when the service itself deduplicates on the idempotency key.
    supports_idempotency_keys: ClassVar[bool] = False

    @abstractmethod
    async def send(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> ProviderResponse:
        """Hand ``message`` to the service. Raise a ``ProviderError`` subclass on failure."""

    async def close(self) -> None:  # noqa: B027 (optional hook, empty on purpose)
        """Release connections or clients. Called by ``MailingKit.aclose()``."""

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        """Build the provider from ``MAILINGKIT_*`` variables. Override to support it."""
        raise ConfigurationError(f"{cls.__name__} cannot be configured from environment variables")

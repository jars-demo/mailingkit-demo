"""The MailingKit exception hierarchy.

Applications catch these instead of provider SDK exceptions. Every provider adapter maps its
own failures onto the ``ProviderError`` subclasses, so switching providers never changes the
error handling code in the application.

::

    MailingKitError
    ├── ConfigurationError
    ├── ValidationError
    │   ├── InvalidAddressError
    │   └── MessageTooLargeError
    ├── TemplateError
    │   ├── TemplateNotFoundError
    │   ├── TemplateDataError
    │   └── TemplateRenderError
    └── ProviderError                 (.retryable, .provider, .status_code)
        ├── AuthenticationError
        ├── RateLimitError            (.retry_after)
        ├── RecipientRejectedError
        ├── TemporaryProviderError
        └── PermanentProviderError
"""

from __future__ import annotations

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "InvalidAddressError",
    "MailingKitError",
    "MessageTooLargeError",
    "PermanentProviderError",
    "ProviderError",
    "RateLimitError",
    "RecipientRejectedError",
    "TemplateDataError",
    "TemplateError",
    "TemplateNotFoundError",
    "TemplateRenderError",
    "TemporaryProviderError",
    "ValidationError",
]


class MailingKitError(Exception):
    """Base class for every error MailingKit raises."""


class ConfigurationError(MailingKitError):
    """MailingKit or a provider is configured incorrectly."""


class ValidationError(MailingKitError, ValueError):
    """A message failed validation and was not sent."""


class InvalidAddressError(ValidationError):
    """An email address is malformed or unsafe."""


class MessageTooLargeError(ValidationError):
    """A message is larger than the configured limit."""


class TemplateError(MailingKitError):
    """Base class for template problems."""


class TemplateNotFoundError(TemplateError):
    """No template exists with the requested name."""


class TemplateDataError(TemplateError, ValueError):
    """The data passed to a template is missing fields or has the wrong shape."""


class TemplateRenderError(TemplateError):
    """A template failed while rendering."""


class ProviderError(MailingKitError):
    """A provider failed to accept a message.

    ``retryable`` tells the caller (and MailingKit's own retry loop) whether sending the
    same message again could succeed. ``__cause__`` holds the provider's original exception
    for debugging; it is never part of the message text, so secrets in it are not logged.
    """

    default_retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = self.default_retryable if retryable is None else retryable


class AuthenticationError(ProviderError):
    """The provider rejected the credentials."""


class RateLimitError(ProviderError):
    """The provider is throttling requests. Safe to retry after ``retry_after`` seconds."""

    default_retryable = True

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=status_code)
        self.retry_after = retry_after


class RecipientRejectedError(ProviderError):
    """The provider refused one or more recipients."""


class TemporaryProviderError(ProviderError):
    """A transient failure such as a timeout, a dropped connection or a 5xx response."""

    default_retryable = True


class PermanentProviderError(ProviderError):
    """The provider rejected the message and retrying will not help."""

"""MailingKit: a drop-in, provider-agnostic transactional email layer for Python.

::

    from mailingkit import MailingKit

    mail = MailingKit.from_env()
    await mail.send(to="ada@example.com", subject="Welcome", text="Hello Ada")
"""

from importlib.metadata import PackageNotFoundError, version

from mailingkit.config import Secret
from mailingkit.errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidAddressError,
    MailingKitError,
    MessageTooLargeError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    RecipientRejectedError,
    TemplateDataError,
    TemplateError,
    TemplateNotFoundError,
    TemplateRenderError,
    TemporaryProviderError,
    ValidationError,
)
from mailingkit.message import Address, Attachment, EmailMessage
from mailingkit.providers import EmailProvider, register_provider
from mailingkit.results import MailEvent, ProviderResponse, SendResult
from mailingkit.templates import RenderedTemplate, Template, TemplateRenderer
from mailingkit.validation import Limits

try:
    __version__ = version("mailingkit")
except PackageNotFoundError:  # pragma: no cover (running from a source checkout)
    __version__ = "0.0.0"

__all__ = [
    "Address",
    "Attachment",
    "AuthenticationError",
    "ConfigurationError",
    "EmailMessage",
    "EmailProvider",
    "InvalidAddressError",
    "Limits",
    "MailEvent",
    "MailingKitError",
    "MessageTooLargeError",
    "PermanentProviderError",
    "ProviderError",
    "ProviderResponse",
    "RateLimitError",
    "RecipientRejectedError",
    "RenderedTemplate",
    "Secret",
    "SendResult",
    "Template",
    "TemplateDataError",
    "TemplateError",
    "TemplateNotFoundError",
    "TemplateRenderError",
    "TemplateRenderer",
    "TemporaryProviderError",
    "ValidationError",
    "__version__",
    "register_provider",
]

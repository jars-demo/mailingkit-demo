"""Checks every message passes before it reaches a provider."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mailingkit.errors import MessageTooLargeError, ValidationError
from mailingkit.message import EmailMessage

__all__ = ["Limits", "validate_message"]

# RFC 5322 field-name characters, minus ":".
_HEADER_NAME = re.compile(r"^[!-9;-~]+$")
_TAG = re.compile(r"^[A-Za-z0-9_-]{1,256}$")

# Headers MailingKit builds itself. Setting them through ``headers`` would let a caller
# bypass address validation, so they are refused.
RESERVED_HEADERS = frozenset(
    {
        "bcc",
        "cc",
        "content-transfer-encoding",
        "content-type",
        "date",
        "from",
        "message-id",
        "mime-version",
        "reply-to",
        "sender",
        "subject",
        "to",
    }
)


@dataclass(frozen=True, slots=True)
class Limits:
    """Safety limits applied to every message.

    The defaults fit every built-in provider. Raise them only if your provider allows it.
    """

    max_recipients: int = 50
    max_message_bytes: int = 10 * 1024 * 1024
    max_subject_length: int = 998


def _has_line_break(value: str) -> bool:
    return "\r" in value or "\n" in value or "\x00" in value


def estimate_size(message: EmailMessage) -> int:
    """Approximate encoded size in bytes. Attachments are counted as base64."""
    size = len(message.subject.encode("utf-8"))
    size += len((message.html or "").encode("utf-8"))
    size += len((message.text or "").encode("utf-8"))
    size += sum((attachment.size + 2) // 3 * 4 for attachment in message.attachments)
    return size


def validate_message(message: EmailMessage, limits: Limits | None = None) -> None:
    """Raise :class:`ValidationError` if ``message`` is not safe and complete."""
    limits = limits or Limits()

    if message.sender is None:
        raise ValidationError("Message has no sender. Pass sender= or configure default_sender.")
    if not message.recipients:
        raise ValidationError("Message has no recipients")
    if len(message.recipients) > limits.max_recipients:
        raise ValidationError(
            f"Message has {len(message.recipients)} recipients; "
            f"the limit is {limits.max_recipients}"
        )

    if not message.subject.strip():
        raise ValidationError("Message has an empty subject")
    if _has_line_break(message.subject):
        raise ValidationError("Subject must not contain line breaks")
    if len(message.subject) > limits.max_subject_length:
        raise ValidationError(f"Subject is longer than {limits.max_subject_length} characters")

    if not (message.html or message.text):
        raise ValidationError("Message needs an html or a text body")

    for name, value in message.headers.items():
        if not _HEADER_NAME.match(name):
            raise ValidationError(f"Invalid header name: {name!r}")
        if name.lower() in RESERVED_HEADERS:
            raise ValidationError(f"Header {name!r} is set by MailingKit and cannot be overridden")
        if not isinstance(value, str) or _has_line_break(value):
            raise ValidationError(f"Header {name!r} must be a single-line string")

    for key, value in message.tags.items():
        if not _TAG.match(key) or not isinstance(value, str) or not _TAG.match(value):
            raise ValidationError(
                f"Tag {key!r} is invalid: names and values may only use "
                "letters, digits, '_' and '-'"
            )

    size = estimate_size(message)
    if size > limits.max_message_bytes:
        raise MessageTooLargeError(
            f"Message is about {size} bytes; the limit is {limits.max_message_bytes}"
        )

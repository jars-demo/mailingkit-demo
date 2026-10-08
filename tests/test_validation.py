from __future__ import annotations

import pytest

from mailingkit import Attachment, EmailMessage, Limits, MessageTooLargeError, ValidationError
from mailingkit.validation import validate_message


def make(**overrides: object) -> EmailMessage:
    fields: dict[str, object] = {
        "to": "ada@example.com",
        "sender": "app@example.com",
        "subject": "Hello",
        "text": "Body",
    }
    fields.update(overrides)
    return EmailMessage.build(**fields)  # type: ignore[arg-type]


def test_validate_message_accepts_a_complete_message() -> None:
    validate_message(make())


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"sender": None}, "no sender"),
        ({"to": []}, "no recipients"),
        ({"subject": "   "}, "empty subject"),
        ({"subject": "Hi\r\nBcc: victim@example.com"}, "line breaks"),
        ({"text": None}, "html or a text body"),
        ({"headers": {"X-Note": "a\r\nBcc: victim@example.com"}}, "single-line"),
        ({"headers": {"Bad Header": "x"}}, "Invalid header name"),
        ({"headers": {"Bcc": "victim@example.com"}}, "cannot be overridden"),
        ({"tags": {"campaign": "spring sale"}}, "Tag"),
    ],
)
def test_validate_message_rejects_unsafe_or_incomplete_messages(
    overrides: dict[str, object], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        validate_message(make(**overrides))


def test_validate_message_enforces_recipient_limit_at_the_boundary() -> None:
    limits = Limits(max_recipients=2)

    validate_message(make(to=["a@example.com", "b@example.com"]), limits)
    with pytest.raises(ValidationError, match="recipients"):
        validate_message(make(to=["a@example.com", "b@example.com", "c@example.com"]), limits)


def test_validate_message_counts_attachments_as_base64_size() -> None:
    attachment = Attachment("big.bin", b"\0" * 900)

    with pytest.raises(MessageTooLargeError):
        validate_message(make(attachments=[attachment]), Limits(max_message_bytes=1000))

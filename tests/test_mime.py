from __future__ import annotations

import email
from email import policy

from mailingkit import Attachment, EmailMessage
from mailingkit.mime import to_mime


def parse(message: EmailMessage) -> email.message.EmailMessage:
    raw = to_mime(message).as_bytes()
    parsed = email.message_from_bytes(raw, policy=policy.default)
    assert isinstance(parsed, email.message.EmailMessage)
    return parsed


def test_to_mime_builds_text_and_html_alternatives() -> None:
    parsed = parse(
        EmailMessage.build(
            to="ada@example.com",
            sender="app@example.com",
            subject="Hi",
            text="Hi",
            html="<p>Hi</p>",
        )
    )

    assert parsed.get_content_type() == "multipart/alternative"
    assert parsed.get_body(("plain",)).get_content().strip() == "Hi"  # type: ignore[union-attr]
    assert parsed.get_body(("html",)).get_content().strip() == "<p>Hi</p>"  # type: ignore[union-attr]


def test_to_mime_leaves_bcc_out_of_headers() -> None:
    parsed = parse(
        EmailMessage.build(
            to="ada@example.com",
            bcc="audit@example.com",
            sender="app@example.com",
            subject="Hi",
            text="x",
        )
    )

    assert parsed["Bcc"] is None
    assert "audit@example.com" not in parsed.as_string()


def test_to_mime_encodes_non_ascii_subject_and_names() -> None:
    parsed = parse(
        EmailMessage.build(
            to="Zoë <zoe@example.com>", sender="app@example.com", subject="Café ☕", text="x"
        )
    )

    assert parsed["Subject"] == "Café ☕"
    assert parsed["To"].addresses[0].display_name == "Zoë"


def test_to_mime_adds_regular_and_inline_attachments() -> None:
    parsed = parse(
        EmailMessage.build(
            to="ada@example.com",
            sender="app@example.com",
            subject="Hi",
            text="x",
            html='<img src="cid:logo">',
            attachments=[
                Attachment("logo.png", b"\x89PNG", content_id="logo"),
                Attachment("terms.pdf", b"%PDF"),
            ],
        )
    )

    parts = {part.get_filename(): part for part in parsed.walk() if part.get_filename()}
    assert parts["logo.png"]["Content-ID"] == "<logo>"
    assert parts["terms.pdf"].get_content_disposition() == "attachment"

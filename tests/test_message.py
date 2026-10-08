from __future__ import annotations

import pytest

from mailingkit import Address, Attachment, EmailMessage, InvalidAddressError, ValidationError


def test_address_parse_reads_display_name_and_email() -> None:
    address = Address.parse('"Jane Doe" <jane@example.com>')

    assert address == Address("jane@example.com", "Jane Doe")


def test_address_parse_lowercases_only_the_domain() -> None:
    address = Address.parse("Jane.Doe@Example.COM")

    assert address.email == "Jane.Doe@example.com"


def test_address_str_quotes_display_names_that_need_it() -> None:
    address = Address("jane@example.com", "Doe, Jane")

    assert str(address) == '"Doe, Jane" <jane@example.com>'


@pytest.mark.parametrize(
    "value",
    [
        "",
        "plainaddress",
        "@example.com",
        "jane@",
        "jane@localhost",
        "jane..doe@example.com",
        ".jane@example.com",
        "jane@-example.com",
        "jane doe@example.com",
        "a@b@example.com",
        "jane@example.com\r\nBcc: victim@example.com",
        "Jane <jane@example.com>\nBcc: victim@example.com",
    ],
)
def test_address_parse_rejects_invalid_or_unsafe_addresses(value: str) -> None:
    with pytest.raises(InvalidAddressError):
        Address.parse(value)


def test_address_rejects_line_breaks_in_display_name() -> None:
    with pytest.raises(InvalidAddressError):
        Address("jane@example.com", "Jane\r\nBcc: victim@example.com")


def test_address_accepts_internationalized_domain() -> None:
    address = Address.parse("info@bücher.example")

    assert address.email == "info@bücher.example"


def test_attachment_guesses_content_type_from_filename() -> None:
    attachment = Attachment("invoice.pdf", b"%PDF")

    assert attachment.content_type == "application/pdf"


def test_attachment_repr_does_not_include_content() -> None:
    attachment = Attachment("secret.txt", b"top secret contents")

    assert "top secret" not in repr(attachment)


@pytest.mark.parametrize("filename", ["", "../etc/passwd", "dir\\file.txt", "a\r\nb.txt", ".."])
def test_attachment_rejects_unsafe_filenames(filename: str) -> None:
    with pytest.raises(ValidationError):
        Attachment(filename, b"data")


def test_attachment_from_path_reads_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "report.csv"
    path.write_bytes(b"a,b\n1,2\n")

    attachment = Attachment.from_path(path)

    assert (attachment.filename, attachment.content) == ("report.csv", b"a,b\n1,2\n")


def test_email_message_build_normalizes_loose_input() -> None:
    message = EmailMessage.build(to="ada@example.com", cc=["Bob <bob@example.com>"], subject="Hi")

    assert message.recipients == (Address("ada@example.com"), Address("bob@example.com", "Bob"))


def test_email_message_headers_cannot_be_mutated_after_creation() -> None:
    message = EmailMessage.build(to="ada@example.com", headers={"X-Trace": "1"})

    with pytest.raises(TypeError):
        message.headers["X-Trace"] = "2"  # type: ignore[index]

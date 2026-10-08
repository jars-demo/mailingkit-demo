"""The provider-independent message model.

Providers only ever receive an :class:`EmailMessage`. It is immutable, so a message cannot be
changed by a hook or a provider after it has been validated.
"""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from email.utils import formataddr
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from mailingkit.errors import InvalidAddressError, ValidationError

__all__ = ["Address", "AddressInput", "Attachment", "EmailMessage", "Recipients"]

_LOCAL_PART = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_NAME_AND_EMAIL = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]*)>$", re.DOTALL)
_CONTENT_TYPE = re.compile(r"^[A-Za-z0-9][\w.+-]*/[A-Za-z0-9][\w.+-]*$")
_CONTROL_CHARS = ("\r", "\n", "\x00")


def _has_control_chars(value: str) -> bool:
    return any(char in value for char in _CONTROL_CHARS)


def _check_email(email: str) -> str:
    """Validate an address and return it with the domain lowercased."""
    if _has_control_chars(email) or any(char.isspace() for char in email):
        raise InvalidAddressError(
            f"Email address contains whitespace or control characters: {email!r}"
        )
    if len(email) > 254:
        raise InvalidAddressError("Email address is longer than 254 characters")
    local, at, domain = email.rpartition("@")
    if not at or not local or not domain or "@" in local:
        raise InvalidAddressError(f"Invalid email address: {email!r}")
    if len(local) > 64 or not _LOCAL_PART.match(local):
        raise InvalidAddressError(f"Invalid local part in email address: {email!r}")
    if local.startswith(".") or local.endswith(".") or ".." in local:
        raise InvalidAddressError(f"Invalid dots in email address: {email!r}")
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidAddressError(f"Invalid domain in email address: {email!r}") from exc
    labels = ascii_domain.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL.match(label) for label in labels):
        raise InvalidAddressError(f"Invalid domain in email address: {email!r}")
    return f"{local}@{domain.lower()}"


@dataclass(frozen=True, slots=True)
class Address:
    """A single mailbox, optionally with a display name.

    >>> Address.parse("Jane Doe <jane@example.com>")
    Address(email='jane@example.com', name='Jane Doe')
    """

    email: str
    name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", _check_email(self.email))
        if self.name is not None:
            if _has_control_chars(self.name):
                raise InvalidAddressError("Display name contains line breaks or control characters")
            object.__setattr__(self, "name", self.name.strip() or None)

    @classmethod
    def parse(cls, value: AddressInput) -> Address:
        """Build an address from ``"a@example.com"``, ``"Name <a@example.com>"`` or an Address."""
        if isinstance(value, Address):
            return value
        if not isinstance(value, str):
            raise InvalidAddressError(
                f"Expected an email address string, got {type(value).__name__}"
            )
        text = value.strip()
        if _has_control_chars(text):
            raise InvalidAddressError("Email address contains line breaks or control characters")
        match = _NAME_AND_EMAIL.match(text)
        if match:
            name = match.group("name").strip().strip('"').strip()
            return cls(email=match.group("email").strip(), name=name or None)
        return cls(email=text)

    def __str__(self) -> str:
        return formataddr((self.name, self.email)) if self.name else self.email


AddressInput: TypeAlias = str | Address
Recipients: TypeAlias = AddressInput | Iterable[AddressInput]


def _parse_recipients(value: Recipients | None) -> tuple[Address, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, Address)):
        return (Address.parse(value),)
    return tuple(Address.parse(item) for item in value)


@dataclass(frozen=True, slots=True, repr=False)
class Attachment:
    """A file attached to a message.

    Set ``content_id`` to reference the attachment inline from HTML as ``<img src="cid:...">``.
    """

    filename: str
    content: bytes
    content_type: str | None = None
    content_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.content, str):
            object.__setattr__(self, "content", self.content.encode("utf-8"))
        if not isinstance(self.content, (bytes, bytearray)):
            raise ValidationError("Attachment content must be bytes")
        object.__setattr__(self, "content", bytes(self.content))
        name = self.filename
        if (
            not name
            or len(name) > 255
            or _has_control_chars(name)
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
        ):
            raise ValidationError(f"Unsafe attachment filename: {name!r}")
        content_type = (
            self.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        if not _CONTENT_TYPE.match(content_type):
            raise ValidationError(f"Invalid attachment content type: {content_type!r}")
        object.__setattr__(self, "content_type", content_type)
        if self.content_id is not None and (
            not self.content_id or _has_control_chars(self.content_id) or "<" in self.content_id
        ):
            raise ValidationError(f"Invalid attachment content_id: {self.content_id!r}")

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        filename: str | None = None,
        content_type: str | None = None,
        content_id: str | None = None,
    ) -> Attachment:
        """Read a file from disk. ``filename`` defaults to the file's own name."""
        file_path = Path(path)
        return cls(
            filename=filename or file_path.name,
            content=file_path.read_bytes(),
            content_type=content_type,
            content_id=content_id,
        )

    @property
    def size(self) -> int:
        return len(self.content)

    def __repr__(self) -> str:
        return (
            f"Attachment(filename={self.filename!r}, content_type={self.content_type!r}, "
            f"size={self.size})"
        )


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """A fully rendered message, ready to hand to a provider.

    Most applications never build this directly: :meth:`MailingKit.send` and
    :meth:`MailingKit.send_template` create it. Use :meth:`build` when you do need one, since
    it accepts plain strings for addresses.
    """

    to: tuple[Address, ...] = ()
    subject: str = ""
    html: str | None = None
    text: str | None = None
    sender: Address | None = None
    cc: tuple[Address, ...] = ()
    bcc: tuple[Address, ...] = ()
    reply_to: tuple[Address, ...] = ()
    headers: Mapping[str, str] = field(default_factory=dict)
    attachments: tuple[Attachment, ...] = ()
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce loose input so a message built by hand is still normalized and immutable.
        for name in ("to", "cc", "bcc", "reply_to"):
            object.__setattr__(self, name, _parse_recipients(getattr(self, name)))
        if self.sender is not None:
            object.__setattr__(self, "sender", Address.parse(self.sender))
        object.__setattr__(self, "attachments", tuple(self.attachments))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "tags", MappingProxyType(dict(self.tags)))

    @classmethod
    def build(
        cls,
        *,
        to: Recipients | None = None,
        subject: str = "",
        html: str | None = None,
        text: str | None = None,
        sender: AddressInput | None = None,
        cc: Recipients | None = None,
        bcc: Recipients | None = None,
        reply_to: Recipients | None = None,
        headers: Mapping[str, str] | None = None,
        attachments: Iterable[Attachment] | None = None,
        tags: Mapping[str, str] | None = None,
    ) -> EmailMessage:
        """Create a message from loosely typed input such as plain address strings."""
        return cls(
            to=_parse_recipients(to),
            subject=subject,
            html=html,
            text=text,
            sender=Address.parse(sender) if sender is not None else None,
            cc=_parse_recipients(cc),
            bcc=_parse_recipients(bcc),
            reply_to=_parse_recipients(reply_to),
            headers=dict(headers or {}),
            attachments=tuple(attachments or ()),
            tags=dict(tags or {}),
        )

    @property
    def recipients(self) -> tuple[Address, ...]:
        """Every envelope recipient: ``to``, ``cc`` and ``bcc``."""
        return self.to + self.cc + self.bcc

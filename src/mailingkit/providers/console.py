"""Prints emails instead of sending them. The default provider, so development is safe."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Mapping
from typing import Self, TextIO

from mailingkit.config import env_bool
from mailingkit.message import EmailMessage
from mailingkit.providers.base import EmailProvider
from mailingkit.results import ProviderResponse

__all__ = ["ConsoleProvider"]


class ConsoleProvider(EmailProvider):
    """Writes each message to a stream (stdout by default). Nothing leaves the machine.

    Environment: ``MAILINGKIT_CONSOLE_SHOW_HTML=true`` prints the HTML body as well.
    """

    name = "console"

    def __init__(self, stream: TextIO | None = None, *, show_html: bool = False) -> None:
        self.stream = stream
        self.show_html = show_html

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        return cls(show_html=env_bool(environ, "CONSOLE_SHOW_HTML", False))

    def format(self, message: EmailMessage) -> str:
        rule = "-" * 72
        lines = ["=" * 72, "MailingKit console provider: this email was NOT sent", rule]
        lines.append(f"From:     {message.sender}")
        for label, addresses in (
            ("To", message.to),
            ("Cc", message.cc),
            ("Bcc", message.bcc),
            ("Reply-To", message.reply_to),
        ):
            if addresses:
                lines.append(f"{label + ':':<10}{', '.join(str(a) for a in addresses)}")
        lines.append(f"Subject:  {message.subject}")
        for header, value in message.headers.items():
            lines.append(f"{header}: {value}")
        if message.tags:
            lines.append("Tags:     " + ", ".join(f"{k}={v}" for k, v in message.tags.items()))
        for attachment in message.attachments:
            lines.append(
                f"Attached: {attachment.filename} "
                f"({attachment.content_type}, {attachment.size} bytes)"
            )
        lines.append(rule)
        lines.append(message.text if message.text is not None else "(no text body)")
        if self.show_html and message.html is not None:
            lines.extend([rule, message.html])
        lines.append("=" * 72)
        return "\n".join(lines) + "\n"

    async def send(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> ProviderResponse:
        stream = self.stream or sys.stdout
        stream.write(self.format(message))
        stream.flush()
        return ProviderResponse(provider_message_id=f"console-{uuid.uuid4().hex}")

"""Writes each message as an ``.eml`` file, which any mail client can open as a preview."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from mailingkit.config import env_str
from mailingkit.message import EmailMessage
from mailingkit.mime import to_mime
from mailingkit.providers.base import EmailProvider
from mailingkit.results import ProviderResponse

__all__ = ["FileProvider"]


class FileProvider(EmailProvider):
    """Saves messages to a folder instead of sending them.

    Environment: ``MAILINGKIT_FILE_DIR`` (default ``.mailingkit/outbox``).
    """

    name = "file"

    def __init__(self, directory: str | Path = ".mailingkit/outbox") -> None:
        self.directory = Path(directory)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        return cls(env_str(environ, "FILE_DIR", ".mailingkit/outbox") or ".mailingkit/outbox")

    def _write(self, path: Path, data: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def send(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> ProviderResponse:
        message_id = uuid.uuid4().hex
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.directory / f"{stamp}-{message_id[:12]}.eml"
        await asyncio.to_thread(self._write, path, to_mime(message).as_bytes())
        return ProviderResponse(provider_message_id=str(path))

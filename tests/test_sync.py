from __future__ import annotations

import asyncio

from mailingkit import MailingKit, SyncMailingKit
from mailingkit.providers import MemoryProvider
from tests.conftest import TEMPLATES


def test_sync_client_sends_from_plain_code() -> None:
    provider = MemoryProvider()

    with SyncMailingKit(provider, default_sender="app@example.com") as mail:
        result = mail.send(to="ada@example.com", subject="Hi", text="x")

    assert (result.attempts, len(provider.outbox)) == (1, 1)


def test_sync_client_works_inside_a_running_event_loop() -> None:
    provider = MemoryProvider()
    mail = SyncMailingKit(provider, default_sender="app@example.com")

    async def caller() -> None:
        mail.send(to="ada@example.com", subject="Hi", text="x")

    asyncio.run(caller())
    mail.close()

    assert len(provider.outbox) == 1


def test_sync_client_wraps_existing_async_client_and_renders_templates() -> None:
    provider = MemoryProvider()
    client = MailingKit(provider, default_sender="app@example.com", templates=TEMPLATES)
    mail = SyncMailingKit.wrap(client)

    mail.send_template("plain", {"name": "Ada"}, to="ada@example.com")
    mail.close()

    assert provider.last.text == "Hello Ada"


def test_sync_client_close_is_safe_when_nothing_was_sent() -> None:
    mail = SyncMailingKit(MemoryProvider())

    mail.close()

from __future__ import annotations

import asyncio
import logging

import pytest

from mailingkit import (
    NO_RETRY,
    Address,
    AuthenticationError,
    ConfigurationError,
    EmailMessage,
    EmailProvider,
    MailEvent,
    MailingKit,
    PermanentProviderError,
    ProviderResponse,
    RateLimitError,
    TemporaryProviderError,
    ValidationError,
)
from mailingkit.providers import ConsoleProvider, MemoryProvider
from tests.conftest import FAST_RETRY, TEMPLATES


async def test_send_hands_message_to_provider_with_default_sender(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    result = await mail.send(to="ada@example.com", subject="Hello", text="Hi Ada")

    assert provider.last.sender == Address("app@example.com", "Example App")
    assert (result.provider, result.provider_message_id, result.attempts) == (
        "memory",
        "memory-1",
        1,
    )


async def test_send_generates_text_body_from_html(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    await mail.send(to="ada@example.com", subject="Hello", html="<p>Hi <b>Ada</b></p>")

    assert provider.last.text == "Hi Ada"


async def test_send_explicit_sender_overrides_default(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    await mail.send(to="ada@example.com", subject="Hi", text="x", sender="billing@example.com")

    assert provider.last.sender == Address("billing@example.com")


async def test_send_raises_validation_error_before_reaching_provider(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    with pytest.raises(ValidationError):
        await mail.send(to="ada@example.com", subject="Hi\nBcc: x@example.com", text="x")

    assert provider.outbox == []


async def test_send_template_renders_and_sends(mail: MailingKit, provider: MemoryProvider) -> None:
    await mail.send_template(
        "welcome",
        {"name": "Ada", "product": "Acme", "login_url": "https://acme.test"},
        to="ada@example.com",
    )

    assert provider.last.subject == "Welcome to Acme, Ada"


async def test_send_template_without_templates_configured_raises(provider: MemoryProvider) -> None:
    mail = MailingKit(provider, default_sender="app@example.com")

    with pytest.raises(ConfigurationError, match="No templates configured"):
        await mail.send_template("welcome", {}, to="ada@example.com")


async def test_redirect_to_replaces_every_recipient_and_records_originals(
    provider: MemoryProvider,
) -> None:
    mail = MailingKit(provider, default_sender="app@example.com", redirect_to="qa@example.com")

    result = await mail.send(
        to="ada@example.com", cc="bob@example.com", bcc="eve@example.com", subject="Hi", text="x"
    )

    assert provider.last.recipients == (Address("qa@example.com"),)
    assert provider.last.headers["X-MailingKit-Original-To"] == (
        "ada@example.com, bob@example.com, eve@example.com"
    )
    assert result.redirected is True


async def test_validate_returns_the_message_the_provider_would_receive(mail: MailingKit) -> None:
    prepared = mail.validate(
        EmailMessage.build(to="ada@example.com", subject="Hi", html="<p>x</p>")
    )

    assert (prepared.sender, prepared.text) == (Address("app@example.com", "Example App"), "x")


async def test_transient_errors_are_retried_until_success(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    provider.fail_next(TemporaryProviderError("timeout"), TemporaryProviderError("timeout"))

    result = await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert result.attempts == 3


async def test_retries_stop_at_max_attempts(mail: MailingKit, provider: MemoryProvider) -> None:
    provider.fail_next(*(TemporaryProviderError("down") for _ in range(3)))

    with pytest.raises(TemporaryProviderError):
        await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert provider.outbox == []


async def test_permanent_errors_are_not_retried(mail: MailingKit, provider: MemoryProvider) -> None:
    provider.fail_next(AuthenticationError("bad key"))
    events: list[MailEvent] = []
    mail.hooks.append(events.append)

    with pytest.raises(AuthenticationError) as raised:
        await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert raised.value.provider == "memory"
    assert [(e.name, e.attempt) for e in events] == [("mail.failed", 1)]


async def test_rate_limit_waits_for_retry_after(
    provider: MemoryProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    mail = MailingKit(provider, default_sender="app@example.com")
    provider.fail_next(RateLimitError("slow down", retry_after=2.5))

    await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert delays == [2.5]


async def test_unexpected_provider_exceptions_are_normalized() -> None:
    class BrokenProvider(EmailProvider):
        name = "broken"

        async def send(self, message, *, idempotency_key=None):  # type: ignore[no-untyped-def]
            raise KeyError("oops")

    mail = MailingKit(BrokenProvider(), default_sender="app@example.com", retry=NO_RETRY)

    with pytest.raises(PermanentProviderError, match="broken") as raised:
        await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert isinstance(raised.value.__cause__, KeyError)


async def test_same_idempotency_key_sends_only_once(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    first = await mail.send(to="ada@example.com", subject="Hi", text="x", idempotency_key="k-1")
    second = await mail.send(to="ada@example.com", subject="Hi", text="x", idempotency_key="k-1")

    assert len(provider.outbox) == 1
    assert (second.id, second.duplicate, first.duplicate) == (first.id, True, False)


async def test_concurrent_sends_with_same_key_send_only_once() -> None:
    class SlowProvider(MemoryProvider):
        async def send(self, message, *, idempotency_key=None):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0.01)
            return await super().send(message, idempotency_key=idempotency_key)

    provider = SlowProvider()
    mail = MailingKit(provider, default_sender="app@example.com")

    await asyncio.gather(
        *(
            mail.send(to="a@example.com", subject="Hi", text="x", idempotency_key="k")
            for _ in range(5)
        )
    )

    assert len(provider.outbox) == 1


async def test_idempotency_key_is_passed_to_provider(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    await mail.send(to="ada@example.com", subject="Hi", text="x", idempotency_key="order-42")

    assert provider.idempotency_keys == ["order-42"]


async def test_invalid_idempotency_key_is_rejected(mail: MailingKit) -> None:
    with pytest.raises(ValidationError, match="idempotency_key"):
        await mail.send(to="ada@example.com", subject="Hi", text="x", idempotency_key="a\nb")


async def test_hooks_receive_retry_and_sent_events_without_personal_data(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    events: list[MailEvent] = []

    async def async_hook(event: MailEvent) -> None:
        events.append(event)

    mail.hooks.append(async_hook)
    provider.fail_next(TemporaryProviderError("blip"))

    await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert [e.name for e in events] == ["mail.retry", "mail.sent"]
    assert "ada@example.com" not in repr(events)


async def test_failing_hook_does_not_break_sending(
    mail: MailingKit, provider: MemoryProvider
) -> None:
    def bad_hook(event: MailEvent) -> None:
        raise RuntimeError("hook bug")

    mail.hooks.append(bad_hook)

    await mail.send(to="ada@example.com", subject="Hi", text="x")

    assert len(provider.outbox) == 1


async def test_logs_do_not_contain_recipients_or_subject(
    mail: MailingKit, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="mailingkit")

    await mail.send(to="ada@example.com", subject="Private matter", text="x")

    assert "mail.sent" in caplog.text
    assert "ada@example.com" not in caplog.text
    assert "Private matter" not in caplog.text


def test_from_env_defaults_to_console_provider() -> None:
    mail = MailingKit.from_env({})

    assert isinstance(mail.provider, ConsoleProvider)


def test_from_env_reads_sender_templates_and_redirect() -> None:
    mail = MailingKit.from_env(
        {
            "MAILINGKIT_PROVIDER": "memory",
            "MAILINGKIT_FROM_EMAIL": "app@example.com",
            "MAILINGKIT_FROM_NAME": "Example",
            "MAILINGKIT_TEMPLATES_DIR": str(TEMPLATES),
            "MAILINGKIT_REDIRECT_TO": "qa@example.com",
            "MAILINGKIT_MAX_ATTEMPTS": "5",
        }
    )

    assert isinstance(mail.provider, MemoryProvider)
    assert mail.default_sender == Address("app@example.com", "Example")
    assert mail.redirect_to == Address("qa@example.com")
    assert mail.retry.max_attempts == 5
    assert mail.templates is not None


def test_from_env_keyword_overrides_win() -> None:
    mail = MailingKit.from_env({"MAILINGKIT_PROVIDER": "memory"}, retry=FAST_RETRY)

    assert mail.retry is FAST_RETRY


def test_from_env_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigurationError, match="Unknown provider 'nope'"):
        MailingKit.from_env({"MAILINGKIT_PROVIDER": "nope"})


async def test_async_context_manager_closes_provider() -> None:
    closed: list[bool] = []

    class ClosingProvider(MemoryProvider):
        async def close(self) -> None:
            closed.append(True)

    async with MailingKit(ClosingProvider()):
        pass

    assert closed == [True]


async def test_custom_provider_plugs_in() -> None:
    class RecordingProvider(EmailProvider):
        name = "recording"

        def __init__(self) -> None:
            self.subjects: list[str] = []

        async def send(self, message, *, idempotency_key=None):  # type: ignore[no-untyped-def]
            self.subjects.append(message.subject)
            return ProviderResponse(provider_message_id="rec-1")

    provider = RecordingProvider()
    mail = MailingKit(provider, default_sender="app@example.com")

    result = await mail.send(to="ada@example.com", subject="Custom", text="x")

    assert (provider.subjects, result.provider) == (["Custom"], "recording")

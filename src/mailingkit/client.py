"""The MailingKit client: the one object applications talk to."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import logging
import os
import threading
import uuid
import weakref
from collections.abc import Coroutine, Iterable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any, Self, TypeVar

from mailingkit._html_text import html_to_text
from mailingkit.config import Settings
from mailingkit.errors import (
    ConfigurationError,
    PermanentProviderError,
    ProviderError,
    ValidationError,
)
from mailingkit.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from mailingkit.message import Address, AddressInput, Attachment, EmailMessage, Recipients
from mailingkit.providers import ConsoleProvider, EmailProvider, create_provider
from mailingkit.results import EventName, Hook, MailEvent, SendResult
from mailingkit.retry import RetryPolicy
from mailingkit.templates import RenderedTemplate, Template, TemplateRenderer
from mailingkit.validation import Limits, validate_message

__all__ = ["MailingKit", "SyncMailingKit"]

logger = logging.getLogger("mailingkit")

T = TypeVar("T")

ORIGINAL_RECIPIENTS_HEADER = "X-MailingKit-Original-To"


def _check_idempotency_key(key: str) -> None:
    if not key or len(key) > 256 or not key.isprintable() or not key.isascii():
        raise ValidationError("idempotency_key must be 1 to 256 printable ASCII characters")


class MailingKit:
    """Send email through any provider.

    ::

        mail = MailingKit.from_env()
        await mail.send(to="ada@example.com", subject="Welcome", text="Hello Ada")
        await mail.send_template("welcome", {"name": "Ada"}, to="ada@example.com")

    With no provider configured, MailingKit uses :class:`ConsoleProvider`, which prints
    messages and sends nothing.
    """

    def __init__(
        self,
        provider: EmailProvider | None = None,
        *,
        default_sender: AddressInput | None = None,
        templates: str | Path | TemplateRenderer | None = None,
        retry: RetryPolicy | None = None,
        idempotency_store: IdempotencyStore | None = None,
        idempotency_ttl: float = 24 * 60 * 60,
        redirect_to: AddressInput | None = None,
        limits: Limits | None = None,
        hooks: Iterable[Hook] = (),
    ) -> None:
        self.provider: EmailProvider = provider or ConsoleProvider()
        self.default_sender = Address.parse(default_sender) if default_sender is not None else None
        if templates is None or isinstance(templates, TemplateRenderer):
            self.templates = templates
        else:
            self.templates = TemplateRenderer(templates)
        self.retry = retry or RetryPolicy()
        self.idempotency_store: IdempotencyStore = idempotency_store or InMemoryIdempotencyStore()
        self.idempotency_ttl = idempotency_ttl
        self.redirect_to = Address.parse(redirect_to) if redirect_to is not None else None
        self.limits = limits or Limits()
        self.hooks: list[Hook] = list(hooks)
        self._key_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **overrides: Any) -> Self:
        """Build a client from ``MAILINGKIT_*`` environment variables.

        Keyword arguments override what the environment says, for example
        ``MailingKit.from_env(hooks=[my_hook])``.
        """
        env = os.environ if environ is None else environ
        settings = Settings.from_env(env)
        provider = overrides.pop("provider", None) or create_provider(settings.provider, env)
        options: dict[str, Any] = {
            "default_sender": settings.default_sender,
            "templates": settings.templates_dir,
            "redirect_to": settings.redirect_to,
            "retry": RetryPolicy(max_attempts=settings.max_attempts),
        }
        options.update(overrides)
        return cls(provider, **options)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.provider!r})"

    # Building and checking messages

    def render(self, template: Template[Any] | str, data: object | None = None) -> RenderedTemplate:
        """Render a template without sending it. Useful for previews and tests."""
        if self.templates is None:
            raise ConfigurationError(
                "No templates configured. Pass templates= or set MAILINGKIT_TEMPLATES_DIR."
            )
        return self.templates.render(template, data)

    def validate(self, message: EmailMessage) -> EmailMessage:
        """Return the exact message that would be handed to the provider, or raise.

        Applies the default sender, generates a text body from HTML when there is none,
        validates everything, then applies ``redirect_to``.
        """
        changes: dict[str, Any] = {}
        if message.sender is None and self.default_sender is not None:
            changes["sender"] = self.default_sender
        if message.text is None and message.html:
            changes["text"] = html_to_text(message.html)
        if changes:
            message = dataclasses.replace(message, **changes)
        validate_message(message, self.limits)
        if self.redirect_to is not None:
            original = ", ".join(a.email for a in message.recipients)
            message = dataclasses.replace(
                message,
                to=(self.redirect_to,),
                cc=(),
                bcc=(),
                headers={**message.headers, ORIGINAL_RECIPIENTS_HEADER: original},
            )
        return message

    # Sending

    async def send(
        self,
        *,
        to: Recipients,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        sender: AddressInput | None = None,
        cc: Recipients | None = None,
        bcc: Recipients | None = None,
        reply_to: Recipients | None = None,
        headers: Mapping[str, str] | None = None,
        attachments: Iterable[Attachment] | None = None,
        tags: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Send a message you have already written."""
        message = EmailMessage.build(
            to=to,
            subject=subject,
            html=html,
            text=text,
            sender=sender,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            headers=headers,
            attachments=attachments,
            tags=tags,
        )
        return await self._deliver(message, idempotency_key, template=None)

    async def send_template(
        self,
        template: Template[T] | str,
        data: T | Mapping[str, Any] | None = None,
        *,
        to: Recipients,
        sender: AddressInput | None = None,
        cc: Recipients | None = None,
        bcc: Recipients | None = None,
        reply_to: Recipients | None = None,
        headers: Mapping[str, str] | None = None,
        attachments: Iterable[Attachment] | None = None,
        tags: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        """Render a template with ``data`` and send it."""
        rendered = self.render(template, data)
        message = EmailMessage.build(
            to=to,
            subject=rendered.subject,
            html=rendered.html,
            text=rendered.text,
            sender=sender,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            headers=headers,
            attachments=attachments,
            tags=tags,
        )
        name = template if isinstance(template, str) else template.name
        return await self._deliver(message, idempotency_key, template=name)

    async def send_message(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> SendResult:
        """Send a prebuilt :class:`EmailMessage`."""
        return await self._deliver(message, idempotency_key, template=None)

    async def _deliver(
        self, message: EmailMessage, idempotency_key: str | None, *, template: str | None
    ) -> SendResult:
        prepared = self.validate(message)
        if idempotency_key is None:
            return await self._send_with_retry(prepared, None, template)

        _check_idempotency_key(idempotency_key)
        lock = self._key_locks.get(idempotency_key)
        if lock is None:
            lock = self._key_locks[idempotency_key] = asyncio.Lock()
        async with lock:
            previous = await self.idempotency_store.get(idempotency_key)
            if previous is not None:
                result = dataclasses.replace(previous, duplicate=True)
                await self._emit("mail.duplicate", result.id, 0, template, prepared, result=result)
                return result
            result = await self._send_with_retry(prepared, idempotency_key, template)
            await self.idempotency_store.set(idempotency_key, result, self.idempotency_ttl)
            return result

    async def _send_with_retry(
        self, message: EmailMessage, idempotency_key: str | None, template: str | None
    ) -> SendResult:
        send_id = uuid.uuid4().hex
        provider_name = self.provider.name
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self.provider.send(message, idempotency_key=idempotency_key)
            except ProviderError as error:
                if error.provider is None:
                    error.provider = provider_name
                if self.retry.should_retry(attempt, error):
                    delay = self.retry.delay(attempt, error)
                    logger.warning(
                        "mail.retry id=%s provider=%s attempt=%d delay=%.2fs error=%s",
                        send_id,
                        provider_name,
                        attempt,
                        delay,
                        type(error).__name__,
                    )
                    await self._emit("mail.retry", send_id, attempt, template, message, error=error)
                    await asyncio.sleep(delay)
                    continue
                await self._fail(send_id, attempt, template, message, error)
                raise
            except Exception as exc:
                # A custom provider raised something unexpected: normalize it.
                wrapped = PermanentProviderError(
                    f"Provider {provider_name!r} raised {type(exc).__name__}",
                    provider=provider_name,
                )
                await self._fail(send_id, attempt, template, message, wrapped)
                raise wrapped from exc

            result = SendResult(
                id=send_id,
                provider=provider_name,
                provider_message_id=response.provider_message_id,
                attempts=attempt,
                idempotency_key=idempotency_key,
                redirected=self.redirect_to is not None,
            )
            logger.info(
                "mail.sent id=%s provider=%s template=%s attempts=%d",
                send_id,
                provider_name,
                template or "-",
                attempt,
            )
            await self._emit("mail.sent", send_id, attempt, template, message, result=result)
            return result

    async def _fail(
        self,
        send_id: str,
        attempt: int,
        template: str | None,
        message: EmailMessage,
        error: Exception,
    ) -> None:
        logger.error(
            "mail.failed id=%s provider=%s template=%s attempts=%d error=%s",
            send_id,
            self.provider.name,
            template or "-",
            attempt,
            type(error).__name__,
        )
        await self._emit("mail.failed", send_id, attempt, template, message, error=error)

    async def _emit(
        self,
        name: EventName,
        send_id: str,
        attempt: int,
        template: str | None,
        message: EmailMessage,
        *,
        error: Exception | None = None,
        result: SendResult | None = None,
    ) -> None:
        if not self.hooks:
            return
        event = MailEvent(
            name=name,
            id=send_id,
            provider=self.provider.name,
            attempt=attempt,
            template=template,
            recipient_count=len(message.recipients),
            error=error,
            result=result,
        )
        for hook in self.hooks:
            try:
                outcome = hook(event)
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception:
                logger.exception("MailingKit hook %r failed on %s", hook, name)

    # Lifecycle

    async def aclose(self) -> None:
        await self.provider.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


class SyncMailingKit:
    """A blocking wrapper for code that is not async: Django views, scripts, Celery tasks.

    It runs the async client on one private event loop in a background thread, so it is safe
    to call from any thread, including one that already has its own running event loop.
    """

    def __init__(self, provider: EmailProvider | None = None, **options: Any) -> None:
        self.client = MailingKit(provider, **options)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **overrides: Any) -> Self:
        return cls.wrap(MailingKit.from_env(environ, **overrides))

    @classmethod
    def wrap(cls, client: MailingKit) -> Self:
        """Wrap an existing async client so sync and async code share one configuration."""
        instance = cls.__new__(cls)
        instance.client = client
        instance._loop = None
        instance._thread = None
        instance._lock = threading.Lock()
        return instance

    def __repr__(self) -> str:
        return f"{type(self).__name__}(provider={self.client.provider!r})"

    def _run(self, coroutine: Coroutine[Any, Any, T]) -> T:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop.run_forever, name="mailingkit", daemon=True
                )
                self._thread.start()
            loop = self._loop
        return asyncio.run_coroutine_threadsafe(coroutine, loop).result()

    def render(self, template: Template[Any] | str, data: object | None = None) -> RenderedTemplate:
        return self.client.render(template, data)

    def validate(self, message: EmailMessage) -> EmailMessage:
        return self.client.validate(message)

    def send(
        self,
        *,
        to: Recipients,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        sender: AddressInput | None = None,
        cc: Recipients | None = None,
        bcc: Recipients | None = None,
        reply_to: Recipients | None = None,
        headers: Mapping[str, str] | None = None,
        attachments: Iterable[Attachment] | None = None,
        tags: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        return self._run(
            self.client.send(
                to=to,
                subject=subject,
                html=html,
                text=text,
                sender=sender,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                headers=headers,
                attachments=attachments,
                tags=tags,
                idempotency_key=idempotency_key,
            )
        )

    def send_template(
        self,
        template: Template[T] | str,
        data: T | Mapping[str, Any] | None = None,
        *,
        to: Recipients,
        sender: AddressInput | None = None,
        cc: Recipients | None = None,
        bcc: Recipients | None = None,
        reply_to: Recipients | None = None,
        headers: Mapping[str, str] | None = None,
        attachments: Iterable[Attachment] | None = None,
        tags: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> SendResult:
        return self._run(
            self.client.send_template(
                template,
                data,
                to=to,
                sender=sender,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                headers=headers,
                attachments=attachments,
                tags=tags,
                idempotency_key=idempotency_key,
            )
        )

    def send_message(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> SendResult:
        return self._run(self.client.send_message(message, idempotency_key=idempotency_key))

    def close(self) -> None:
        try:
            self._run(self.client.aclose())
        finally:
            with self._lock:
                loop, thread = self._loop, self._thread
                self._loop = self._thread = None
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
                if thread is not None:
                    thread.join()
                loop.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

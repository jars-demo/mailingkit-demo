"""A Django email backend that routes ``django.core.mail`` through MailingKit.

Existing ``send_mail()`` calls, password reset emails and admin error emails all start going
through MailingKit's validation, providers and retries without changing any code.

Django 6.1 and newer::

    MAILERS = {
        "default": {
            "BACKEND": "mailingkit.contrib.django.EmailBackend",
            "OPTIONS": {"client": "myproject.mail.mail"},   # optional
        },
    }

Older Django::

    EMAIL_BACKEND = "mailingkit.contrib.django.EmailBackend"
    MAILINGKIT_CLIENT = "myproject.mail.mail"                # optional

Without a ``client`` the backend builds one with ``MailingKit.from_env()``. A client is a
dotted path to a ``MailingKit`` or ``SyncMailingKit`` instance you configured yourself.
"""

from __future__ import annotations

import importlib
import logging
import threading
from collections.abc import Sequence
from email.mime.base import MIMEBase
from typing import Any

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage as DjangoEmailMessage

from mailingkit.client import MailingKit, SyncMailingKit
from mailingkit.errors import MailingKitError
from mailingkit.message import Attachment, EmailMessage

__all__ = ["EmailBackend", "to_mailingkit_message"]

logger = logging.getLogger("mailingkit")

_DJANGO_PLACEHOLDER_SENDER = "webmaster@localhost"

_clients: dict[str | None, SyncMailingKit] = {}
_clients_lock = threading.Lock()


def _load_client(path: str | None) -> SyncMailingKit:
    """Return the shared client for ``path``, building it once per process."""
    with _clients_lock:
        if path not in _clients:
            if path:
                module_name, _, attribute = path.rpartition(".")
                configured = getattr(importlib.import_module(module_name), attribute)
                if isinstance(configured, MailingKit):
                    configured = SyncMailingKit.wrap(configured)
                if not isinstance(configured, SyncMailingKit):
                    raise TypeError(f"{path} must be a MailingKit or SyncMailingKit instance")
                _clients[path] = configured
            else:
                _clients[path] = SyncMailingKit.from_env()
        return _clients[path]


def _attachment(item: Any) -> Attachment:
    if isinstance(item, MIMEBase):
        raise MailingKitError("MIMEBase attachments are not supported; attach bytes instead")
    filename, content, mimetype = item
    return Attachment(filename=filename, content=content, content_type=mimetype)


def to_mailingkit_message(message: DjangoEmailMessage) -> EmailMessage:
    """Convert a Django ``EmailMessage`` or ``EmailMultiAlternatives``."""
    html: str | None = None
    text: str | None = None
    if message.content_subtype == "html":
        html = message.body
    else:
        text = message.body
    for content, mimetype in getattr(message, "alternatives", ()):
        if mimetype == "text/html":
            html = str(content)

    # Django's built-in DEFAULT_FROM_EMAIL is not a deliverable address; let MailingKit's
    # default sender apply instead.
    sender = message.from_email if message.from_email != _DJANGO_PLACEHOLDER_SENDER else None

    return EmailMessage.build(
        to=message.to,
        cc=message.cc,
        bcc=message.bcc,
        reply_to=message.reply_to,
        sender=sender or None,
        subject=str(message.subject),
        html=html,
        text=text,
        headers={str(k): str(v) for k, v in message.extra_headers.items()},
        attachments=[_attachment(item) for item in message.attachments],
    )


class EmailBackend(BaseEmailBackend):  # type: ignore[misc]
    """Send Django email through MailingKit."""

    def __init__(self, *args: Any, client: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Django 6.1 keeps fail_silently private and deprecates reading it from the base class.
        state = vars(self)
        self.fail_silently = bool(state.get("fail_silently", state.get("_fail_silently", False)))
        self.client_path = client or getattr(settings, "MAILINGKIT_CLIENT", None)

    def send_messages(self, email_messages: Sequence[DjangoEmailMessage]) -> int:
        client = _load_client(self.client_path)
        sent = 0
        for message in email_messages:
            if not message.recipients():
                continue
            try:
                client.send_message(to_mailingkit_message(message))
            except MailingKitError:
                if not self.fail_silently:
                    raise
                logger.exception("MailingKit Django backend failed to send a message")
            else:
                sent += 1
        return sent

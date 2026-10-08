from __future__ import annotations

from collections.abc import Iterator

import pytest

django = pytest.importorskip("django")

from django.conf import settings  # noqa: E402

if not settings.configured:
    settings.configure(
        MAILERS={
            "default": {
                "BACKEND": "mailingkit.contrib.django.EmailBackend",
                "OPTIONS": {"client": "tests.test_django.CLIENT"},
            }
        },
        DEFAULT_FROM_EMAIL="webmaster@localhost",
    )
    django.setup()

from django.core import mail as django_mail  # noqa: E402

from mailingkit import Address, MailingKit  # noqa: E402
from mailingkit.contrib import django as backend_module  # noqa: E402
from mailingkit.providers import MemoryProvider  # noqa: E402

PROVIDER = MemoryProvider()
CLIENT = MailingKit(PROVIDER, default_sender="App <app@example.com>")


@pytest.fixture(autouse=True)
def fresh_outbox() -> Iterator[None]:
    PROVIDER.clear()
    yield
    PROVIDER.clear()


def test_send_mail_goes_through_mailingkit() -> None:
    count = django_mail.send_mail("Hello", "Plain body", None, ["ada@example.com"])

    assert count == 1
    assert PROVIDER.last.subject == "Hello"
    assert PROVIDER.last.text == "Plain body"


def test_placeholder_django_sender_is_replaced_by_mailingkit_default() -> None:
    django_mail.send_mail("Hello", "Body", None, ["ada@example.com"])

    assert PROVIDER.last.sender == Address("app@example.com", "App")


def test_html_alternative_and_attachments_are_converted() -> None:
    message = django_mail.EmailMultiAlternatives(
        "Report",
        "Text version",
        "reports@example.com",
        ["ada@example.com"],
        bcc=["audit@example.com"],
    )
    message.attach_alternative("<p>HTML version</p>", "text/html")
    message.attach("report.csv", "a,b\n", "text/csv")

    message.send()

    sent = PROVIDER.last
    assert (sent.html, sent.text) == ("<p>HTML version</p>", "Text version")
    assert sent.bcc == (Address("audit@example.com"),)
    assert sent.attachments[0].filename == "report.csv"


def test_fail_silently_swallows_mailingkit_errors() -> None:
    backend = backend_module.EmailBackend(client="tests.test_django.CLIENT")
    backend.fail_silently = True
    message = django_mail.EmailMessage("Bad\nsubject", "Body", None, ["ada@example.com"])

    count = backend.send_messages([message])

    assert count == 0


def test_errors_propagate_by_default() -> None:
    message = django_mail.EmailMessage("Hi", "Body", "not-an-address", ["ada@example.com"])

    with pytest.raises(ValueError, match="Invalid email"):
        message.send()

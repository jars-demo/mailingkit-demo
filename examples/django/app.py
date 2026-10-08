"""MailingKit as the email backend of a Django project, in one file.

Nothing in the application changes: Django's own send_mail() and EmailMultiAlternatives go
through MailingKit once the backend is configured. Run from the repository root:

    uv run python examples/django/app.py

In a real project the two settings below go in settings.py.
"""

from __future__ import annotations

import django
from django.conf import settings

# Django 6.1 introduced MAILERS; older versions use EMAIL_BACKEND.
if django.VERSION >= (6, 1):
    mail_settings = {"MAILERS": {"default": {"BACKEND": "mailingkit.contrib.django.EmailBackend"}}}
else:
    mail_settings = {"EMAIL_BACKEND": "mailingkit.contrib.django.EmailBackend"}

settings.configure(
    DEFAULT_FROM_EMAIL="Acme HR <people@example.com>",
    **mail_settings,
)
django.setup()

from django.core.mail import EmailMultiAlternatives, send_mail  # noqa: E402


def main() -> None:
    # Plain Django code: it has no idea MailingKit exists.
    send_mail(
        subject="Your leave request was approved",
        message="Hi Ada, your leave from 12 to 16 October is approved.",
        from_email=None,
        recipient_list=["ada@example.com"],
    )

    message = EmailMultiAlternatives(
        subject="Payslip for September",
        body="Your September payslip is attached.",
        to=["ada@example.com"],
    )
    message.attach_alternative(
        "<p>Your <strong>September</strong> payslip is attached.</p>", "text/html"
    )
    message.attach("payslip-2026-09.txt", "Net pay: 1000.00\n", "text/plain")
    message.send()


if __name__ == "__main__":
    main()

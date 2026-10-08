"""Send through any SMTP server, using only the standard library."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from collections.abc import Mapping
from email.message import EmailMessage as MIMEMessage
from typing import Literal, Self

from mailingkit.config import Secret, env_float, env_int, env_required, env_secret, env_str
from mailingkit.errors import (
    AuthenticationError,
    ConfigurationError,
    PermanentProviderError,
    ProviderError,
    RecipientRejectedError,
    TemporaryProviderError,
)
from mailingkit.message import EmailMessage
from mailingkit.mime import to_mime
from mailingkit.providers.base import EmailProvider
from mailingkit.results import ProviderResponse

__all__ = ["SmtpProvider"]

Security = Literal["starttls", "ssl", "none"]
_DEFAULT_PORTS: dict[str, int] = {"starttls": 587, "ssl": 465, "none": 25}


def _reply_text(error: smtplib.SMTPResponseException) -> str:
    raw = error.smtp_error
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    return " ".join(text.split())[:200]


class SmtpProvider(EmailProvider):
    """SMTP with TLS on by default.

    ``security`` is ``"starttls"`` (port 587, the default), ``"ssl"`` (implicit TLS, port 465)
    or ``"none"`` (plain text, meant for local tools such as Mailpit). Credentials are refused
    over an unencrypted connection.

    Environment: ``MAILINGKIT_SMTP_HOST`` (required), ``MAILINGKIT_SMTP_PORT``,
    ``MAILINGKIT_SMTP_USERNAME``, ``MAILINGKIT_SMTP_PASSWORD``, ``MAILINGKIT_SMTP_SECURITY``,
    ``MAILINGKIT_SMTP_TIMEOUT``.
    """

    name = "smtp"

    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        username: str | None = None,
        password: str | Secret | None = None,
        security: Security = "starttls",
        timeout: float = 30.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if security not in _DEFAULT_PORTS:
            raise ConfigurationError(
                f"SMTP security must be starttls, ssl or none, got {security!r}"
            )
        if (username or password) and security == "none":
            raise ConfigurationError(
                "Refusing to send SMTP credentials over an unencrypted connection; "
                "use security='starttls' or 'ssl'"
            )
        if bool(username) != bool(password):
            raise ConfigurationError("SMTP username and password must be set together")
        self.host = host
        self.port = port or _DEFAULT_PORTS[security]
        self.username = username
        self._password = (
            password if isinstance(password, Secret) or password is None else Secret(password)
        )
        self.security: Security = security
        self.timeout = timeout
        self._ssl_context = ssl_context

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        security = (env_str(environ, "SMTP_SECURITY", "starttls") or "starttls").lower()
        if security not in _DEFAULT_PORTS:
            raise ConfigurationError(
                f"MAILINGKIT_SMTP_SECURITY must be starttls, ssl or none, got {security!r}"
            )
        return cls(
            host=env_required(environ, "SMTP_HOST"),
            port=env_int(environ, "SMTP_PORT", _DEFAULT_PORTS[security]),
            username=env_str(environ, "SMTP_USERNAME"),
            password=env_secret(environ, "SMTP_PASSWORD"),
            security=security,  # type: ignore[arg-type]
            timeout=env_float(environ, "SMTP_TIMEOUT", 30.0),
        )

    def __repr__(self) -> str:
        return f"SmtpProvider(host={self.host!r}, port={self.port}, security={self.security!r})"

    def _context(self) -> ssl.SSLContext:
        return self._ssl_context or ssl.create_default_context()

    def _connect(self) -> smtplib.SMTP:
        if self.security == "ssl":
            return smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout, context=self._context()
            )
        return smtplib.SMTP(self.host, self.port, timeout=self.timeout)

    def _send_sync(self, mime: MIMEMessage, sender: str, recipients: list[str]) -> None:
        with self._connect() as client:
            if self.security == "starttls":
                client.starttls(context=self._context())
            if self.username and self._password:
                client.login(self.username, self._password.get_secret_value())
            client.send_message(mime, from_addr=sender, to_addrs=recipients)

    def _translate(self, error: Exception) -> ProviderError:
        if isinstance(error, smtplib.SMTPAuthenticationError):
            return AuthenticationError(f"SMTP login failed ({error.smtp_code})", provider=self.name)
        if isinstance(error, smtplib.SMTPRecipientsRefused):
            return RecipientRejectedError(
                f"SMTP server refused {len(error.recipients)} recipient(s)", provider=self.name
            )
        if isinstance(error, smtplib.SMTPNotSupportedError):
            return PermanentProviderError(
                f"SMTP server does not support this: {error}", provider=self.name
            )
        if isinstance(error, smtplib.SMTPResponseException):
            code = error.smtp_code
            text = f"SMTP server replied {code}: {_reply_text(error)}"
            if 400 <= code < 500:
                return TemporaryProviderError(text, status_code=code, provider=self.name)
            return PermanentProviderError(text, status_code=code, provider=self.name)
        if isinstance(error, ssl.SSLCertVerificationError):
            return PermanentProviderError(
                f"TLS certificate verification failed: {error}", provider=self.name
            )
        if isinstance(error, (smtplib.SMTPException, OSError)):
            return TemporaryProviderError(
                f"SMTP connection failed: {type(error).__name__}", provider=self.name
            )
        return PermanentProviderError(
            f"SMTP send failed: {type(error).__name__}", provider=self.name
        )

    async def send(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> ProviderResponse:
        if message.sender is None:
            raise ConfigurationError("Message has no sender")
        mime = to_mime(message)
        recipients = [address.email for address in message.recipients]
        try:
            await asyncio.to_thread(self._send_sync, mime, message.sender.email, recipients)
        except Exception as exc:
            raise self._translate(exc) from exc
        return ProviderResponse(provider_message_id=str(mime["Message-ID"]))

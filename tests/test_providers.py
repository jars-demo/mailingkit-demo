from __future__ import annotations

import email
import io
import json
import smtplib
from email import policy
from typing import Any, ClassVar

import httpx
import pytest

from mailingkit import (
    Attachment,
    AuthenticationError,
    ConfigurationError,
    EmailMessage,
    EmailProvider,
    PermanentProviderError,
    ProviderResponse,
    RateLimitError,
    RecipientRejectedError,
    Secret,
    TemporaryProviderError,
    register_provider,
)
from mailingkit.providers import (
    ConsoleProvider,
    FileProvider,
    ResendProvider,
    SmtpProvider,
    create_provider,
    get_provider_class,
)

MESSAGE = EmailMessage.build(
    to="Ada <ada@example.com>",
    cc="bob@example.com",
    bcc="audit@example.com",
    sender="App <app@example.com>",
    subject="Your receipt",
    html="<p>Total: $5</p>",
    text="Total: $5",
    tags={"category": "receipt"},
    attachments=[Attachment("receipt.txt", b"total 5")],
)


async def test_console_provider_prints_message_without_sending() -> None:
    stream = io.StringIO()

    await ConsoleProvider(stream).send(MESSAGE)

    output = stream.getvalue()
    assert "NOT sent" in output
    assert "Subject:  Your receipt" in output
    assert "receipt.txt (text/plain, 7 bytes)" in output


async def test_file_provider_writes_a_readable_eml_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    response = await FileProvider(tmp_path).send(MESSAGE)

    (path,) = tmp_path.glob("*.eml")
    parsed = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    assert response.provider_message_id == str(path)
    assert parsed["Subject"] == "Your receipt"


# SMTP


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []
    error: Exception | None = None

    def __init__(self, host: str, port: int, timeout: float, **kwargs: Any) -> None:
        self.host, self.port = host, port
        self.calls: list[str] = []
        self.sent: tuple[Any, str, list[str]] | None = None
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.calls.append(f"login:{username}:{password}")

    def send_message(self, msg: Any, from_addr: str, to_addrs: list[str]) -> dict[str, Any]:
        if FakeSMTP.error is not None:
            raise FakeSMTP.error
        self.sent = (msg, from_addr, to_addrs)
        return {}


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.error = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


async def test_smtp_provider_uses_starttls_login_and_envelope_bcc(
    fake_smtp: type[FakeSMTP],
) -> None:
    provider = SmtpProvider("smtp.example.com", username="user", password="pw")

    response = await provider.send(MESSAGE)

    client = fake_smtp.instances[0]
    assert client.port == 587
    assert client.calls == ["starttls", "login:user:pw", "quit"]
    assert client.sent is not None
    mime, envelope_from, recipients = client.sent
    assert (envelope_from, recipients) == (
        "app@example.com",
        ["ada@example.com", "bob@example.com", "audit@example.com"],
    )
    assert mime["Bcc"] is None
    assert response.provider_message_id == mime["Message-ID"]


@pytest.mark.parametrize(
    ("error", "expected", "retryable"),
    [
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), AuthenticationError, False),
        (
            smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no")}),
            RecipientRejectedError,
            False,
        ),
        (smtplib.SMTPDataError(451, b"try later"), TemporaryProviderError, True),
        (smtplib.SMTPDataError(554, b"rejected"), PermanentProviderError, False),
        (smtplib.SMTPServerDisconnected("gone"), TemporaryProviderError, True),
        (ConnectionRefusedError(), TemporaryProviderError, True),
    ],
)
async def test_smtp_provider_maps_errors(
    fake_smtp: type[FakeSMTP], error: Exception, expected: type[Exception], retryable: bool
) -> None:
    fake_smtp.error = error

    with pytest.raises(expected) as raised:
        await SmtpProvider("smtp.example.com", security="ssl").send(MESSAGE)

    assert raised.value.retryable is retryable  # type: ignore[attr-defined]


def test_smtp_provider_refuses_credentials_without_tls() -> None:
    with pytest.raises(ConfigurationError, match="unencrypted"):
        SmtpProvider("smtp.example.com", username="user", password="pw", security="none")


def test_smtp_provider_from_env_hides_password_in_repr() -> None:
    provider = SmtpProvider.from_env(
        {
            "MAILINGKIT_SMTP_HOST": "smtp.example.com",
            "MAILINGKIT_SMTP_USERNAME": "user",
            "MAILINGKIT_SMTP_PASSWORD": "hunter2",
            "MAILINGKIT_SMTP_SECURITY": "ssl",
        }
    )

    assert provider.port == 465
    assert "hunter2" not in repr(provider) + repr(vars(provider))


def test_smtp_provider_from_env_requires_host() -> None:
    with pytest.raises(ConfigurationError, match="MAILINGKIT_SMTP_HOST"):
        SmtpProvider.from_env({})


# Resend


def resend_with(handler: Any) -> ResendProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ResendProvider("re_test_key", client=client)


async def test_resend_provider_posts_payload_with_auth_and_idempotency() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "re_123"})

    response = await resend_with(handler).send(MESSAGE, idempotency_key="order-1")

    body = json.loads(seen[0].content)
    assert response == ProviderResponse(provider_message_id="re_123")
    assert seen[0].headers["Authorization"] == "Bearer re_test_key"
    assert seen[0].headers["Idempotency-Key"] == "order-1"
    assert body["from"] == "App <app@example.com>"
    assert body["bcc"] == ["audit@example.com"]
    assert body["tags"] == [{"name": "category", "value": "receipt"}]
    assert body["attachments"][0]["content"] == "dG90YWwgNQ=="


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthenticationError),
        (422, PermanentProviderError),
        (500, TemporaryProviderError),
        (409, TemporaryProviderError),
    ],
)
async def test_resend_provider_maps_http_errors(status: int, expected: type[Exception]) -> None:
    provider = resend_with(lambda request: httpx.Response(status, json={"message": "nope"}))

    with pytest.raises(expected, match=str(status)):
        await provider.send(MESSAGE)


async def test_resend_provider_reads_retry_after_on_rate_limit() -> None:
    provider = resend_with(lambda request: httpx.Response(429, headers={"retry-after": "3"}))

    with pytest.raises(RateLimitError) as raised:
        await provider.send(MESSAGE)

    assert raised.value.retry_after == 3.0


async def test_resend_provider_maps_network_failure_to_temporary_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(TemporaryProviderError, match="Could not reach Resend"):
        await resend_with(handler).send(MESSAGE)


async def test_resend_errors_never_contain_the_api_key() -> None:
    provider = resend_with(lambda request: httpx.Response(401, json={"message": "invalid"}))

    with pytest.raises(AuthenticationError) as raised:
        await provider.send(MESSAGE)

    assert "re_test_key" not in str(raised.value)
    assert "re_test_key" not in repr(provider)


# Registry


def test_registry_resolves_builtin_providers_by_name() -> None:
    assert get_provider_class("SMTP") is SmtpProvider


def test_registry_accepts_runtime_registration() -> None:
    class InHouseProvider(EmailProvider):
        name = "in-house"

        async def send(self, message, *, idempotency_key=None):  # type: ignore[no-untyped-def]
            return ProviderResponse()

        @classmethod
        def from_env(cls, environ):  # type: ignore[no-untyped-def]
            return cls()

    register_provider("in-house", InHouseProvider)

    assert isinstance(create_provider("in-house", {}), InHouseProvider)


def test_register_provider_rejects_non_providers() -> None:
    with pytest.raises(TypeError):
        register_provider("bad", dict)  # type: ignore[arg-type]


def test_secret_never_reveals_its_value() -> None:
    secret = Secret("hunter2")

    assert "hunter2" not in f"{secret} {secret!r}"
    assert secret.get_secret_value() == "hunter2"

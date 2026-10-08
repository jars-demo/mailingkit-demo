"""Send through the Resend HTTP API (https://resend.com). Requires ``mailingkit[resend]``."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self

from mailingkit.config import Secret, env_float, env_required, env_str
from mailingkit.errors import (
    AuthenticationError,
    ConfigurationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    TemporaryProviderError,
)
from mailingkit.message import EmailMessage
from mailingkit.providers.base import EmailProvider
from mailingkit.results import ProviderResponse

if TYPE_CHECKING:
    import httpx

__all__ = ["ResendProvider"]

DEFAULT_BASE_URL = "https://api.resend.com"


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


class ResendProvider(EmailProvider):
    """Resend adapter. Idempotency keys are passed through, so Resend deduplicates too.

    Environment: ``MAILINGKIT_RESEND_API_KEY`` (required), ``MAILINGKIT_RESEND_BASE_URL``,
    ``MAILINGKIT_RESEND_TIMEOUT``.
    """

    name = "resend"
    supports_idempotency_keys = True

    def __init__(
        self,
        api_key: str | Secret,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        try:
            import httpx
        except ImportError:
            raise ConfigurationError(
                "The Resend provider needs httpx: pip install 'mailingkit[resend]'"
            ) from None
        if not api_key:
            raise ConfigurationError("Resend API key is empty")
        self._api_key = api_key if isinstance(api_key, Secret) else Secret(api_key)
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> Self:
        return cls(
            api_key=Secret(env_required(environ, "RESEND_API_KEY")),
            base_url=env_str(environ, "RESEND_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            timeout=env_float(environ, "RESEND_TIMEOUT", 30.0),
        )

    def __repr__(self) -> str:
        return f"ResendProvider(base_url={self.base_url!r})"

    @staticmethod
    def payload(message: EmailMessage) -> dict[str, Any]:
        """The JSON body Resend expects for ``POST /emails``."""
        body: dict[str, Any] = {
            "from": str(message.sender),
            "to": [str(a) for a in message.to],
            "subject": message.subject,
        }
        if message.cc:
            body["cc"] = [str(a) for a in message.cc]
        if message.bcc:
            body["bcc"] = [str(a) for a in message.bcc]
        if message.reply_to:
            body["reply_to"] = [str(a) for a in message.reply_to]
        if message.html is not None:
            body["html"] = message.html
        if message.text is not None:
            body["text"] = message.text
        if message.headers:
            body["headers"] = dict(message.headers)
        if message.tags:
            body["tags"] = [{"name": k, "value": v} for k, v in message.tags.items()]
        if message.attachments:
            body["attachments"] = [
                {
                    "filename": a.filename,
                    "content": base64.b64encode(a.content).decode("ascii"),
                    "content_type": a.content_type,
                    **({"content_id": a.content_id} if a.content_id else {}),
                }
                for a in message.attachments
            ]
        return body

    def _error(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        try:
            detail = str(response.json().get("message", ""))[:200]
        except ValueError:
            detail = ""
        text = f"Resend returned {status}" + (f": {detail}" if detail else "")
        common: dict[str, Any] = {"provider": self.name, "status_code": status}
        if status in (401, 403):
            return AuthenticationError(text, **common)
        if status == 429:
            return RateLimitError(
                text, retry_after=_retry_after(response.headers.get("retry-after")), **common
            )
        if status == 409 or status >= 500:
            # 409 means a request with the same idempotency key is still in flight.
            return TemporaryProviderError(text, **common)
        return PermanentProviderError(text, **common)

    async def send(
        self, message: EmailMessage, *, idempotency_key: str | None = None
    ) -> ProviderResponse:
        import httpx

        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._client.post(
                f"{self.base_url}/emails", json=self.payload(message), headers=headers
            )
        except httpx.TimeoutException as exc:
            raise TemporaryProviderError("Resend request timed out", provider=self.name) from exc
        except httpx.TransportError as exc:
            raise TemporaryProviderError(
                f"Could not reach Resend: {type(exc).__name__}", provider=self.name
            ) from exc
        if response.is_success:
            try:
                provider_id = response.json().get("id")
            except ValueError:
                provider_id = None
            return ProviderResponse(provider_message_id=provider_id)
        raise self._error(response)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

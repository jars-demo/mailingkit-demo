"""Configuration from environment variables, and a secret type that never prints itself.

Every variable uses the ``MAILINGKIT_`` prefix so it cannot collide with other mail libraries
(Flask-Mail, for example, reads ``MAIL_SERVER``).

========================== ==================================================== ===========
Variable                   Meaning                                              Default
========================== ==================================================== ===========
MAILINGKIT_PROVIDER        console, memory, file, smtp, resend, or a plugin     console
MAILINGKIT_FROM_EMAIL      default sender address
MAILINGKIT_FROM_NAME       default sender display name
MAILINGKIT_TEMPLATES_DIR   folder holding your templates
MAILINGKIT_REDIRECT_TO     send every email to this address instead (staging)
MAILINGKIT_MAX_ATTEMPTS    attempts per send for transient failures             3
========================== ==================================================== ===========

Provider variables (``MAILINGKIT_SMTP_*``, ``MAILINGKIT_RESEND_*``) are documented on each
provider.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from mailingkit.errors import ConfigurationError
from mailingkit.message import Address

__all__ = ["PREFIX", "Secret", "Settings"]

PREFIX = "MAILINGKIT_"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class Secret:
    """Wraps a credential so it never appears in a repr, a log line or a traceback."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('**********')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def env_str(environ: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    value = environ.get(PREFIX + name)
    if value is None or not value.strip():
        return default
    return value.strip()


def env_required(environ: Mapping[str, str], name: str) -> str:
    value = env_str(environ, name)
    if value is None:
        raise ConfigurationError(f"{PREFIX}{name} is required")
    return value


def env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    value = env_str(environ, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ConfigurationError(f"{PREFIX}{name} must be an integer, got {value!r}") from None


def env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    value = env_str(environ, name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        raise ConfigurationError(f"{PREFIX}{name} must be a number, got {value!r}") from None


def env_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    value = environ.get(PREFIX + name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ConfigurationError(f"{PREFIX}{name} must be true or false, got {value!r}")


def env_secret(environ: Mapping[str, str], name: str) -> Secret | None:
    value = env_str(environ, name)
    return Secret(value) if value else None


@dataclass(frozen=True, slots=True)
class Settings:
    """The provider-independent settings, read with :meth:`from_env`."""

    provider: str = "console"
    default_sender: Address | None = None
    templates_dir: str | None = None
    redirect_to: Address | None = None
    max_attempts: int = 3

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = _env(environ)
        from_email = env_str(env, "FROM_EMAIL")
        from_name = env_str(env, "FROM_NAME")
        if from_name and not from_email:
            raise ConfigurationError(f"{PREFIX}FROM_NAME is set but {PREFIX}FROM_EMAIL is not")
        redirect = env_str(env, "REDIRECT_TO")
        try:
            sender = Address(from_email, from_name) if from_email else None
            redirect_to = Address.parse(redirect) if redirect else None
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
        max_attempts = env_int(env, "MAX_ATTEMPTS", 3)
        if max_attempts < 1:
            raise ConfigurationError(f"{PREFIX}MAX_ATTEMPTS must be at least 1")
        return cls(
            provider=(env_str(env, "PROVIDER") or "console").lower(),
            default_sender=sender,
            templates_dir=env_str(env, "TEMPLATES_DIR"),
            redirect_to=redirect_to,
            max_attempts=max_attempts,
        )

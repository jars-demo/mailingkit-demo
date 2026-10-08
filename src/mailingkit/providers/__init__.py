"""Provider adapters and the registry that finds them by name.

Built-in names: ``console``, ``memory``, ``file``, ``smtp``, ``resend``.

Third-party packages can make a provider available by name through an entry point::

    [project.entry-points."mailingkit.providers"]
    my-provider = "my_package.provider:MyProvider"

after which ``MAILINGKIT_PROVIDER=my-provider`` selects it.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from mailingkit.errors import ConfigurationError
from mailingkit.providers.base import EmailProvider
from mailingkit.providers.console import ConsoleProvider
from mailingkit.providers.file import FileProvider
from mailingkit.providers.memory import MemoryProvider
from mailingkit.providers.smtp import SmtpProvider

if TYPE_CHECKING:
    from mailingkit.providers.resend import ResendProvider

__all__ = [
    "ConsoleProvider",
    "EmailProvider",
    "FileProvider",
    "MemoryProvider",
    "ResendProvider",
    "SmtpProvider",
    "create_provider",
    "get_provider_class",
    "register_provider",
]

ENTRY_POINT_GROUP = "mailingkit.providers"

_BUILTIN: dict[str, str] = {
    "console": "mailingkit.providers.console:ConsoleProvider",
    "memory": "mailingkit.providers.memory:MemoryProvider",
    "file": "mailingkit.providers.file:FileProvider",
    "smtp": "mailingkit.providers.smtp:SmtpProvider",
    "resend": "mailingkit.providers.resend:ResendProvider",
}
_registered: dict[str, type[EmailProvider]] = {}


def register_provider(name: str, provider_class: type[EmailProvider]) -> None:
    """Make a provider selectable by name at runtime, for example from ``MAILINGKIT_PROVIDER``."""
    if not (isinstance(provider_class, type) and issubclass(provider_class, EmailProvider)):
        raise TypeError("provider_class must be a subclass of EmailProvider")
    _registered[name.lower()] = provider_class


def _import(target: str) -> Any:
    module_name, _, attribute = target.partition(":")
    return getattr(importlib.import_module(module_name), attribute)


def get_provider_class(name: str) -> type[EmailProvider]:
    """Find a provider by name: runtime registrations, then built-ins, then entry points."""
    key = name.lower()
    if key in _registered:
        return _registered[key]
    if key in _BUILTIN:
        provider_class: type[EmailProvider] = _import(_BUILTIN[key])
        return provider_class
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        if entry_point.name.lower() == key:
            loaded = entry_point.load()
            if not (isinstance(loaded, type) and issubclass(loaded, EmailProvider)):
                raise ConfigurationError(f"Entry point {name!r} is not an EmailProvider subclass")
            return loaded
    available = sorted(
        {*_BUILTIN, *_registered, *(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP))}
    )
    raise ConfigurationError(f"Unknown provider {name!r}. Available: {', '.join(available)}")


def create_provider(name: str, environ: Mapping[str, str]) -> EmailProvider:
    """Build a provider by name, configured from ``MAILINGKIT_*`` variables."""
    return get_provider_class(name).from_env(environ)


def __getattr__(name: str) -> Any:
    # ResendProvider is loaded lazily so ``import mailingkit`` never needs httpx.
    if name == "ResendProvider":
        return _import(_BUILTIN["resend"])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

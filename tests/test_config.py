from __future__ import annotations

import pytest

from mailingkit import Address, ConfigurationError
from mailingkit.config import Settings


def test_settings_defaults_to_console_with_no_environment() -> None:
    settings = Settings.from_env({})

    assert settings == Settings(provider="console")


def test_settings_treats_blank_values_as_unset() -> None:
    settings = Settings.from_env({"MAILINGKIT_PROVIDER": "  ", "MAILINGKIT_FROM_EMAIL": ""})

    assert (settings.provider, settings.default_sender) == ("console", None)


def test_settings_combines_from_email_and_name() -> None:
    settings = Settings.from_env(
        {"MAILINGKIT_FROM_EMAIL": "app@example.com", "MAILINGKIT_FROM_NAME": "Example"}
    )

    assert settings.default_sender == Address("app@example.com", "Example")


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"MAILINGKIT_FROM_NAME": "Example"}, "FROM_EMAIL is not"),
        ({"MAILINGKIT_FROM_EMAIL": "not-an-address"}, "Invalid email"),
        ({"MAILINGKIT_MAX_ATTEMPTS": "three"}, "must be an integer"),
        ({"MAILINGKIT_MAX_ATTEMPTS": "0"}, "at least 1"),
    ],
)
def test_settings_reports_bad_configuration_clearly(environ: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(environ)

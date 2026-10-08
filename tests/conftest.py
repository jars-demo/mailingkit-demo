from __future__ import annotations

from pathlib import Path

import pytest

from mailingkit import MailingKit, RetryPolicy
from mailingkit.providers import MemoryProvider

TEMPLATES = Path(__file__).parent / "fixtures" / "templates"

# Retries without waiting, so retry tests stay fast and deterministic.
FAST_RETRY = RetryPolicy(max_attempts=3, initial_delay=0, max_delay=0, jitter=False)


@pytest.fixture
def provider() -> MemoryProvider:
    return MemoryProvider()


@pytest.fixture
def mail(provider: MemoryProvider) -> MailingKit:
    return MailingKit(
        provider,
        default_sender="Example App <app@example.com>",
        templates=TEMPLATES,
        retry=FAST_RETRY,
    )

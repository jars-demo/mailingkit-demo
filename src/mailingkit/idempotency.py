"""Idempotency: the same key never sends the same email twice.

The default store lives in process memory, which covers retries inside one process. Use a
shared store (Redis, a database) when several processes or machines send with the same keys.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Protocol, runtime_checkable

from mailingkit.results import SendResult

__all__ = ["IdempotencyStore", "InMemoryIdempotencyStore"]


@runtime_checkable
class IdempotencyStore(Protocol):
    """Remembers the result of each idempotent send for ``ttl`` seconds."""

    async def get(self, key: str) -> SendResult | None: ...

    async def set(self, key: str, result: SendResult, ttl: float) -> None: ...


class InMemoryIdempotencyStore:
    """A bounded, process-local store. Oldest entries are evicted first."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, SendResult]] = OrderedDict()

    async def get(self, key: str) -> SendResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, result = entry
        if expires_at < time.monotonic():
            del self._entries[key]
            return None
        return result

    async def set(self, key: str, result: SendResult, ttl: float) -> None:
        self._entries[key] = (time.monotonic() + ttl, result)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)

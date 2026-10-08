"""One lock per key, for work that should happen once per key inside this process."""

import asyncio
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager


class KeyedLocks:
    """Locks created on demand and forgotten when nobody holds or waits for them."""

    def __init__(self) -> None:
        self._entries: dict[Hashable, list] = {}  # key -> [lock, number of users]

    def __len__(self) -> int:
        return len(self._entries)

    @asynccontextmanager
    async def hold(self, key: Hashable) -> AsyncIterator[None]:
        entry = self._entries.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del self._entries[key]

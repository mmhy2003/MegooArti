"""Index files written from a snapshot of a repository, kept in this process.

They are kept by repository and revision: a revision's files are the same whenever
they are written, so once written they are served until the repository changes. A
newer revision of a repository takes the place of the older ones, and what is kept of
all repositories together is bounded by its size: the least recently used goes first.
While one request writes a revision's files, the others that want them wait for those,
and none writes them a second time.

Each process keeps its own; two that write the same revision write the same bytes, but
for the signatures, which are each valid.
"""

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

# How much is kept, of every repository together.
MOST_BYTES = 256 * 1024 * 1024

type Files = dict[str, bytes]


@dataclass(frozen=True)
class Written:
    """The index files of one revision of a repository, and when the revision was made."""

    revision: int
    changed: datetime
    files: Files

    @property
    def size(self) -> int:
        return sum(len(data) for data in self.files.values())


_kept: OrderedDict[uuid.UUID, Written] = OrderedDict()
_writing: dict[tuple[uuid.UUID, int], asyncio.Future[Written]] = {}


def get(repository_id: uuid.UUID, revision: int) -> Written | None:
    """What is kept of this revision, if it is the one kept of its repository."""
    kept = _kept.get(repository_id)
    if kept is None or kept.revision != revision:
        return None
    _kept.move_to_end(repository_id)
    return kept


def put(repository_id: uuid.UUID, written: Written) -> None:
    """Keep a revision's files, unless a newer revision of the repository is kept already."""
    kept = _kept.get(repository_id)
    if kept is not None and kept.revision > written.revision:
        return
    _kept[repository_id] = written
    _kept.move_to_end(repository_id)
    total = sum(one.size for one in _kept.values())
    while total > MOST_BYTES and len(_kept) > 1:
        _, dropped = _kept.popitem(last=False)
        total -= dropped.size


async def written(
    repository_id: uuid.UUID, revision: int, make: Callable[[], Awaitable[Written]]
) -> Written:
    """A revision's files: kept, being written by another request, or written by `make`.

    `make` may write a newer revision than was asked for, if the repository changed
    meanwhile: that is what every request that waited is then given.
    """
    kept = get(repository_id, revision)
    if kept is not None:
        return kept
    key = (repository_id, revision)
    pending = _writing.get(key)
    if pending is None:
        # A task of its own: a request that goes away does not stop it for the others.
        pending = asyncio.ensure_future(make())
        _writing[key] = pending

        def done(task: asyncio.Future[Written]) -> None:
            _writing.pop(key, None)
            if not task.cancelled() and task.exception() is None:
                put(repository_id, task.result())

        pending.add_done_callback(done)
    return await asyncio.shield(pending)


def forget() -> None:
    """Drop everything kept. For tests."""
    _kept.clear()

"""Index files written from what repositories hold, kept in this process.

They are kept by what they are of, a hosted repository or a suite of a group, and by
the revision of it they were written from: a revision's files are the same whenever
they are written, so once written they are served until it changes. A hosted
repository's revision is the number its row counts; a group's is a digest of its
members' own. A newer revision takes the place of the older ones, and what is kept of
all of them together is bounded by its size: the least recently used goes first. While
one request writes a revision's files, the others that want them wait for those, and
none writes them a second time.

Each process keeps its own; two that write the same revision write the same bytes, but
for the signatures, which are each valid.
"""

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime

# How much is kept, of every repository together.
MOST_BYTES = 256 * 1024 * 1024

type Files = dict[str, bytes]
type Revision = int | str


@dataclass(frozen=True)
class Written:
    """The index files of one revision, and when the revision was made.

    `routes` says, for a group, which member answers for a path that is not among the
    files: by its first two parts (a component's architecture), its first (a component),
    or `*` for any other. None says that none does.
    """

    revision: Revision
    changed: datetime
    files: Files
    routes: dict[str, uuid.UUID | None] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return sum(len(data) for data in self.files.values())


_kept: OrderedDict[Hashable, Written] = OrderedDict()
_writing: dict[tuple[Hashable, Revision], asyncio.Future[Written]] = {}


def get(of: Hashable, revision: Revision) -> Written | None:
    """What is kept of this revision, if it is the one kept of what it is of."""
    kept = _kept.get(of)
    if kept is None or kept.revision != revision:
        return None
    _kept.move_to_end(of)
    return kept


def _older(kept: Written, written: Written) -> bool:
    """Whether `written` is of an older revision than what is kept. Digests have no order."""
    numbers = isinstance(kept.revision, int) and isinstance(written.revision, int)
    return numbers and kept.revision > written.revision


def put(of: Hashable, written: Written) -> None:
    """Keep a revision's files, unless a newer revision of the same is kept already."""
    kept = _kept.get(of)
    if kept is not None and _older(kept, written):
        return
    _kept[of] = written
    _kept.move_to_end(of)
    total = sum(one.size for one in _kept.values())
    while total > MOST_BYTES and len(_kept) > 1:
        _, dropped = _kept.popitem(last=False)
        total -= dropped.size


async def written(
    of: Hashable, revision: Revision, make: Callable[[], Awaitable[Written]]
) -> Written:
    """A revision's files: kept, being written by another request, or written by `make`.

    `make` may write a newer revision than was asked for, if the repository changed
    meanwhile: that is what every request that waited is then given.
    """
    kept = get(of, revision)
    if kept is not None:
        return kept
    key = (of, revision)
    pending = _writing.get(key)
    if pending is None:
        # A task of its own: a request that goes away does not stop it for the others.
        pending = asyncio.ensure_future(make())
        _writing[key] = pending

        def done(task: asyncio.Future[Written]) -> None:
            _writing.pop(key, None)
            if not task.cancelled() and task.exception() is None:
                put(of, task.result())

        pending.add_done_callback(done)
    return await asyncio.shield(pending)


def forget() -> None:
    """Drop everything kept. For tests."""
    _kept.clear()

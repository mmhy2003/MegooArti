"""Index files written from what repositories hold, kept in this process.

They are kept by what they are of, a hosted repository or a suite of a group, and by
the revision of it they were written from: a revision's files are the same whenever
they are written, so once written they are served until it changes. A hosted
repository's revision is the number its row counts; a group's is a digest of its
members' own. A newer revision takes the place of the older ones.

What is kept is bounded by its size, the least recently used going first: hosted
repositories and groups each have a budget, so that one large group cannot push every
hosted repository's indexes out. While one request writes a revision's files, the
others that want them wait for those, and none writes them a second time; or, where
they may (`stale`), they are given what is kept meanwhile, and the files are written
behind them. Files that are `held_until` a moment are given for any revision until
then: a group's written while a member could not be checked.

Each process keeps its own; two that write the same revision write the same bytes, but
for the signatures, which are each valid.
"""

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from megooarti.clock import utcnow

log = structlog.get_logger(__name__)

# How much is kept, of hosted repositories and of groups each.
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
    held_until: datetime | None = None

    @property
    def size(self) -> int:
        return sum(len(data) for data in self.files.values())


_kept: OrderedDict[Hashable, Written] = OrderedDict()
_writing: dict[tuple[Hashable, Revision], asyncio.Future[Written]] = {}


def _kind(of: Hashable) -> str:
    """Whose budget something kept is in: a hosted repository's, or a group's suite's."""
    return "group" if isinstance(of, tuple) else "hosted"


def peek(of: Hashable) -> Written | None:
    """What is kept of something, whatever its revision."""
    return _kept.get(of)


def get(of: Hashable, revision: Revision, *, now: datetime | None = None) -> Written | None:
    """What is kept of this revision, or held for any, if it is kept."""
    kept = _kept.get(of)
    if kept is None:
        return None
    held = kept.held_until is not None and (now or utcnow()) < kept.held_until
    if kept.revision != revision and not held:
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
    kind = _kind(of)
    mine = [key for key in _kept if _kind(key) == kind]
    total = sum(_kept[key].size for key in mine)
    for key in mine[:-1]:  # the least recently used first; never the one just kept
        if total <= MOST_BYTES:
            break
        total -= _kept.pop(key).size


async def written(
    of: Hashable,
    revision: Revision,
    make: Callable[[], Awaitable[Written]],
    *,
    stale: bool = False,
) -> Written:
    """A revision's files: kept, being written by another request, or written by `make`.

    `make` may write a newer revision than was asked for, if the repository changed
    meanwhile: that is what every request that waited is then given. With `stale`, a
    request is given what is kept of an older revision, if anything is, and does not
    wait for the new one.
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
            if task.cancelled():
                return
            if task.exception() is not None:
                log.warning("index_not_written", of=str(of), error=repr(task.exception()))
                return
            put(of, task.result())

        pending.add_done_callback(done)
    previous = peek(of) if stale else None
    if previous is not None:
        return previous
    return await asyncio.shield(pending)


def forget() -> None:
    """Drop everything kept. For tests."""
    _kept.clear()

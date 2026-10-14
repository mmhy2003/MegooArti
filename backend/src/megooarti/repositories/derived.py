"""Index files written from a snapshot of a repository, kept in this process.

They are kept by repository and revision: a revision's files are the same whenever
they are written, so once written they are served until the repository changes. A new
revision makes the old files unreachable, and the least recently used go first. Each
process keeps its own; two that write the same revision write the same bytes, but for
the signatures, which are each valid.
"""

import uuid
from collections import OrderedDict

# How many revisions' files are kept, of every repository together.
MOST = 32

type Files = dict[str, bytes]

_kept: OrderedDict[tuple[uuid.UUID, int], Files] = OrderedDict()


def get(repository_id: uuid.UUID, revision: int) -> Files | None:
    key = (repository_id, revision)
    files = _kept.get(key)
    if files is not None:
        _kept.move_to_end(key)
    return files


def put(repository_id: uuid.UUID, revision: int, files: Files) -> None:
    _kept[(repository_id, revision)] = files
    _kept.move_to_end((repository_id, revision))
    while len(_kept) > MOST:
        _kept.popitem(last=False)


def forget() -> None:
    """Drop everything kept. For tests."""
    _kept.clear()

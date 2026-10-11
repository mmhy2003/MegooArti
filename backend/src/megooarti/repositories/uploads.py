"""Uploads that arrive over several requests.

A container client sends a layer in chunks: one request begins the upload, others
append to it, and a last one completes it. Any container may receive any of them, so
the upload is a row in the database and a file in the blob store's temporary area. On
completion the file is hashed where it lies and becomes staged content, without being
copied.

No database connection is held while a chunk arrives or the file is hashed.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.keyed_locks import KeyedLocks
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.models import Repository, Upload
from megooarti.storage.backends import StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore

# Within this process, chunks for one upload are taken one at a time. A client sends
# them in order; this only keeps two that arrive together from interleaving.
_appending = KeyedLocks()


class UnknownUpload(Exception):
    """There is no such upload in progress in this repository."""


class OutOfOrder(Exception):
    """A chunk does not start where the upload ends. `size` is where it does end."""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size


@dataclass(frozen=True)
class Progress:
    id: str
    size: int


def _identifier(upload_id: str) -> uuid.UUID:
    """The ID as it is stored. It also names a file, so nothing else is accepted."""
    try:
        parsed = uuid.UUID(hex=upload_id)
    except ValueError:
        raise UnknownUpload from None
    if parsed.hex != upload_id:
        raise UnknownUpload  # one spelling only: 32 lower-case hexadecimal digits
    return parsed


async def _row(context: RepositoryContext, upload_id: str, key: str) -> Upload:
    found = await context.db.scalar(
        select(Upload).where(
            Upload.id == _identifier(upload_id),
            Upload.repository_id == context.repository.id,
            Upload.key == key,
        )
    )
    if found is None:
        raise UnknownUpload
    return found


async def begin(context: RepositoryContext, key: str) -> str:
    """Begin an upload for `key`, which is the format's to choose. Returns its ID.

    The caller needs `add` or `edit`. The caller commits.
    """
    context.require_write()
    row = Upload(
        repository_id=context.repository.id,
        key=key,
        created_by=context.principal.user.username,
    )
    context.db.add(row)
    await context.db.flush()
    await context.backend.create_upload(row.id.hex)
    return row.id.hex


async def progress(context: RepositoryContext, upload_id: str, key: str) -> Progress:
    """How much of an upload has arrived. Raises UnknownUpload."""
    context.require_write()
    await _row(context, upload_id, key)
    size = await context.backend.upload_size(upload_id)
    if size is None:
        raise UnknownUpload
    return Progress(upload_id, size)


async def append(
    context: RepositoryContext,
    upload_id: str,
    key: str,
    chunks: AsyncIterator[bytes],
    *,
    at: int | None = None,
) -> int:
    """Append a chunk and return the upload's size. The caller commits.

    `at` is where the client says the chunk starts. If the upload does not end
    there, nothing is appended and OutOfOrder says where it does end. A chunk that
    stops arriving half-way is taken back, so the size is always that of whole chunks.
    """
    context.require_write()
    await _row(context, upload_id, key)
    await context.release()  # the chunk needs no connection
    async with _appending.hold(upload_id):
        size = await context.backend.upload_size(upload_id)
        if size is None:
            raise UnknownUpload
        if at is not None and at != size:
            raise OutOfOrder(size)
        size = await context.backend.append(upload_id, chunks)
    await context.db.execute(
        update(Upload).where(Upload.id == _identifier(upload_id)).values(updated_at=utcnow())
    )
    return size


async def complete(context: RepositoryContext, upload_id: str, key: str) -> StagedBlob:
    """Turn an upload into staged content, ready for `context.store`. The caller commits.

    The upload is over whatever the caller then does with the content: store it, or
    `context.discard` it.
    """
    context.require_write()
    await _row(context, upload_id, key)
    await context.release()  # hashing the file needs no connection
    async with _appending.hold(upload_id):
        if await context.backend.upload_size(upload_id) is None:
            raise UnknownUpload
        staged = await context.backend.adopt(upload_id)
    await context.db.execute(delete(Upload).where(Upload.id == _identifier(upload_id)))
    return staged


async def abandon(context: RepositoryContext, upload_id: str, key: str) -> None:
    """Give an upload up. Raises UnknownUpload. The caller commits."""
    context.require_write()
    row = await _row(context, upload_id, key)
    await context.db.delete(row)
    await context.backend.abandon(upload_id)


async def sweep(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
    max_age_seconds: int,
) -> int:
    """Remove uploads nothing was appended to for `max_age_seconds`. Returns how many."""
    cutoff = now - timedelta(seconds=max_age_seconds)
    async with sessionmaker() as db:
        stale = (
            await db.execute(
                select(Upload.id, Repository.blob_store_id)
                .join(Repository, Repository.id == Upload.repository_id)
                .where(Upload.updated_at < cutoff)
            )
        ).all()
        stores = {store.id: store for store in await db.scalars(select(BlobStore))}
        for upload_id, store_id in stale:
            if store_id in stores:
                await backend_for(settings, stores[store_id]).abandon(upload_id.hex)
            await db.execute(delete(Upload).where(Upload.id == upload_id))
        await db.commit()
    return len(stale)

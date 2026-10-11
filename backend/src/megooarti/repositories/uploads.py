"""Uploads that arrive over several requests.

A container client sends a layer in chunks: one request begins the upload, others
append to it, and a last one completes it. Any container may receive any of them, so
the upload is a row in the database and its chunks are files in the blob store's
temporary area. A chunk joins the upload only when all of it has arrived, and is never
written again. On completion the chunks become staged content: one chunk, which is
how clients usually send a layer, is hashed where it lies; several are joined.

An upload is completed by one request only. That request takes the upload's row
before it reads a byte, so every other request for the upload finds none, and what is
hashed is what is stored whatever else arrives meanwhile.

No database connection is held while a chunk arrives or the content is hashed.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.models import Repository, Upload
from megooarti.storage.backends import StagedBlob, UploadFull
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore


class UnknownUpload(Exception):
    """There is no such upload in progress in this repository."""


class OutOfOrder(Exception):
    """A chunk does not start where the upload ends. `size` is where it does end."""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size


class TooManyChunks(Exception):
    """The upload has as many chunks as one may have. Its sender should send larger ones."""


@dataclass(frozen=True)
class Progress:
    id: str
    size: int


def _identifier(upload_id: str) -> uuid.UUID:
    """The ID as it is stored. It also names files, so nothing else is accepted."""
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
    return row.id.hex


async def progress(context: RepositoryContext, upload_id: str, key: str) -> Progress:
    """How much of an upload has arrived. Raises UnknownUpload."""
    context.require_write()
    await _row(context, upload_id, key)
    return Progress(upload_id, await context.backend.upload_size(upload_id))


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
    stops arriving half-way leaves nothing, so the size is always that of whole
    chunks. Raises UnknownUpload, also for an upload that was completed or abandoned
    while the chunk arrived, and TooManyChunks.
    """
    context.require_write()
    await _row(context, upload_id, key)
    await context.release()  # the chunk needs no connection
    try:
        size = await context.backend.append(upload_id, chunks, at=at)
    except UploadFull:
        raise TooManyChunks from None
    if size is None:
        raise OutOfOrder(await context.backend.upload_size(upload_id))
    touched = await context.db.execute(
        update(Upload).where(Upload.id == _identifier(upload_id)).values(updated_at=utcnow())
    )
    if touched.rowcount == 0:
        # Over since the chunk began to arrive. The chunk is nobody's; the sweep takes it.
        raise UnknownUpload
    return size


async def complete(context: RepositoryContext, upload_id: str, key: str) -> StagedBlob:
    """Turn an upload into staged content, ready for `context.store`.

    The upload is over from here on, whatever the caller then does with the content:
    store it, or `context.discard` it. To make that so for every other request, the
    upload's row is removed and that is committed, before the content is read. Nothing
    else may be pending in the caller's transaction.
    """
    context.require_write()
    await _row(context, upload_id, key)
    taken = await context.db.execute(delete(Upload).where(Upload.id == _identifier(upload_id)))
    # This also gives the connection back: hashing the content needs none.
    await context.db.commit()
    if taken.rowcount == 0:
        raise UnknownUpload  # another request completed it first
    try:
        return await context.backend.adopt(upload_id)
    except FileNotFoundError:
        raise UnknownUpload from None  # its chunks were swept from under it


async def abandon(context: RepositoryContext, upload_id: str, key: str) -> None:
    """Give an upload up. Raises UnknownUpload. The caller commits."""
    context.require_write()
    row = await _row(context, upload_id, key)
    await context.db.delete(row)
    await context.db.flush()
    await context.backend.abandon(upload_id)


async def sweep(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
    max_age_seconds: int,
) -> int:
    """Remove uploads nothing was appended to for `max_age_seconds`. Returns how many.

    Chunks that no upload owns any more, and that are as old, go too.
    """
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
            await db.execute(delete(Upload).where(Upload.id == upload_id))
            if store_id in stores:
                await backend_for(settings, stores[store_id]).abandon(upload_id.hex)
        await db.commit()
        # IDs are unique across stores, so one list of what is in progress serves them all.
        in_progress = {upload_id.hex for upload_id in await db.scalars(select(Upload.id))}
        await db.commit()
    for store in stores.values():
        await backend_for(settings, store).sweep_uploads(in_progress, max_age_seconds)
    return len(stale)

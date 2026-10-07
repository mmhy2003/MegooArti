"""Blob records: which content exists in which store, and whether anything uses it."""

import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.config import Settings
from megooarti.repositories.models import Asset
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore

# First key of the two-key advisory lock; the second is derived from the content hash.
_LOCK_NAMESPACE = 0x4D47

# "Some asset uses this blob." For WHERE clauses on Blob.
referenced = exists().where(Asset.blob_id == Blob.id)


def _lock_key(sha256: str) -> int:
    return int.from_bytes(bytes.fromhex(sha256[:8]), "big", signed=True)


async def lock_blob(db: AsyncSession, sha256: str) -> None:
    """Serialise work on one piece of content until this transaction ends.

    Recording an upload and compacting the same content both take this lock, so a blob
    cannot be removed while a new reference to it is being written.
    """
    await db.execute(text(f"SELECT pg_advisory_xact_lock({_LOCK_NAMESPACE}, {_lock_key(sha256)})"))


async def record(
    db: AsyncSession, backend: BlobBackend, blob_store_id: uuid.UUID, staged: StagedBlob
) -> Blob:
    """Make staged content permanent and return its blob row.

    Call inside the transaction that will reference the blob. The file is put in place
    whenever it is missing, whatever the row says, so a lost file is always repaired.
    """
    await lock_blob(db, staged.sha256)
    await backend.commit(staged)
    blob = await db.scalar(
        select(Blob).where(Blob.blob_store_id == blob_store_id, Blob.sha256 == staged.sha256)
    )
    if blob is None:
        blob = Blob(
            blob_store_id=blob_store_id,
            sha256=staged.sha256,
            md5=staged.md5,
            sha1=staged.sha1,
            sha512=staged.sha512,
            size=staged.size,
        )
        db.add(blob)
    else:
        blob.unreferenced_since = None
    await db.flush()
    return blob


async def dereference(db: AsyncSession, blob_ids: Iterable[uuid.UUID], now: datetime) -> None:
    """Mark as unreferenced those of these blobs that no asset uses any more.

    The mark is a hint. Compaction checks again, under the lock, before removing anything.
    """
    ids = list(set(blob_ids))
    if not ids:
        return
    await db.execute(
        update(Blob).where(Blob.id.in_(ids), ~referenced).values(unreferenced_since=now)
    )


async def mark_unreferenced(db: AsyncSession, now: datetime) -> None:
    """Start the grace period for every blob that nothing uses and nothing has marked."""
    await db.execute(
        update(Blob)
        .where(Blob.unreferenced_since.is_(None), ~referenced)
        .values(unreferenced_since=now)
    )


async def compact(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime,
    grace_seconds: int,
    temporary_max_age_seconds: int = 86400,
) -> int:
    """Remove content nothing has used for the grace period. Returns how many blobs.

    Each blob is handled in its own short transaction, under its lock, and checked
    again there: the mark that selected it is only a hint.
    """
    cutoff = now - timedelta(seconds=grace_seconds)
    async with sessionmaker() as db:
        # The marks left by deletes are an optimisation, and concurrent deletes can miss
        # one. Compaction is the source of truth for what is unused.
        await mark_unreferenced(db, now)
        await db.commit()
        stores = {store.id: store for store in await db.scalars(select(BlobStore))}
        candidates = (
            await db.execute(
                select(Blob.id, Blob.sha256, Blob.blob_store_id).where(
                    Blob.unreferenced_since <= cutoff
                )
            )
        ).all()

    removed = 0
    for blob_id, sha256, store_id in candidates:
        async with sessionmaker() as db:
            await lock_blob(db, sha256)
            blob = await db.scalar(
                select(Blob).where(
                    Blob.id == blob_id, Blob.unreferenced_since <= cutoff, ~referenced
                )
            )
            if blob is None:
                # In use again, or already gone. Clear a mark that no longer applies.
                await db.execute(
                    update(Blob)
                    .where(Blob.id == blob_id, referenced)
                    .values(unreferenced_since=None)
                )
                await db.commit()
                continue
            await db.delete(blob)
            await db.flush()
            await backend_for(settings, stores[store_id]).delete(sha256)
            await db.commit()
            removed += 1

    for store in stores.values():
        await backend_for(settings, store).sweep_temporary(temporary_max_age_seconds)
    return removed

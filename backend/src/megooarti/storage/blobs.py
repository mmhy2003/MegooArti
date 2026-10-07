"""Blob records: which content exists in which store, and whether anything uses it."""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import exists, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.models import Asset
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.models import Blob

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

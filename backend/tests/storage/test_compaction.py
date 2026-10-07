import os
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from megooarti.repositories.models import Asset, Repository
from megooarti.storage import blobs
from megooarti.storage.models import Blob

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
DAY = 86400


async def recorded(db, backend, store, stage, content: bytes, unreferenced_for: int | None) -> Blob:
    blob = await blobs.record(db, backend, store.id, await stage(content))
    if unreferenced_for is not None:
        blob.unreferenced_since = NOW - timedelta(seconds=unreferenced_for)
    await db.flush()
    return blob


async def remaining(db) -> set[str]:
    return set(await db.scalars(select(Blob.sha256)))


async def test_only_content_unreferenced_beyond_the_grace_period_is_removed(
    db, sessionmaker, settings, default_store, backend, stage
):
    old = await recorded(db, backend, default_store, stage, b"old", 2 * DAY)
    recent = await recorded(db, backend, default_store, stage, b"recent", 3600)
    unmarked = await recorded(db, backend, default_store, stage, b"unmarked", None)
    await db.commit()

    removed = await blobs.compact(sessionmaker, settings, now=NOW, grace_seconds=DAY)

    assert removed == 1
    assert await remaining(db) == {recent.sha256, unmarked.sha256}
    assert not await backend.exists(old.sha256)
    assert await backend.exists(recent.sha256)


async def test_content_that_is_used_again_is_kept_and_its_mark_cleared(
    db, sessionmaker, settings, default_store, backend, stage
):
    blob = await recorded(db, backend, default_store, stage, b"back in use", 2 * DAY)
    repository = Repository(
        name="files", name_key="files", format="raw", type="hosted", blob_store_id=default_store.id
    )
    db.add(repository)
    await db.flush()
    db.add(
        Asset(
            repository_id=repository.id,
            path="a.bin",
            blob_id=blob.id,
            content_type="application/octet-stream",
            created_by="dana",
        )
    )
    await db.commit()

    removed = await blobs.compact(sessionmaker, settings, now=NOW, grace_seconds=DAY)

    assert removed == 0
    assert await backend.exists(blob.sha256)
    assert await db.scalar(select(Blob.unreferenced_since).where(Blob.id == blob.id)) is None


async def test_old_temporary_files_are_swept(
    db, sessionmaker, settings, default_store, backend, stage
):
    abandoned = await stage(b"never finished")
    in_flight = await stage(b"still arriving")
    two_days_ago = time.time() - 2 * DAY
    os.utime(abandoned.token, (two_days_ago, two_days_ago))

    await blobs.compact(sessionmaker, settings, now=NOW, grace_seconds=DAY)

    assert not os.path.exists(abandoned.token)
    assert os.path.exists(in_flight.token)

from datetime import UTC, datetime

from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Repository
from megooarti.storage import blobs
from megooarti.storage.models import Blob

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def add_asset(db, store, blob: Blob, path: str) -> Asset:
    repository = await db.scalar(select(Repository).where(Repository.name == "files"))
    if repository is None:
        repository = Repository(
            name="files", name_key="files", format="raw", type="hosted", blob_store_id=store.id
        )
        db.add(repository)
        await db.flush()
    asset = Asset(
        repository_id=repository.id,
        path=path,
        blob_id=blob.id,
        content_type="application/octet-stream",
        created_by="dana",
    )
    db.add(asset)
    await db.flush()
    return asset


async def test_record_makes_content_permanent_and_describes_it(db, default_store, backend, stage):
    staged = await stage(b"hello")

    blob = await blobs.record(db, backend, default_store.id, staged)

    assert await backend.exists(staged.sha256)
    assert (blob.sha256, blob.md5, blob.sha1, blob.sha512, blob.size) == (
        staged.sha256,
        staged.md5,
        staged.sha1,
        staged.sha512,
        5,
    )
    assert blob.unreferenced_since is None


async def test_recording_the_same_content_twice_gives_one_blob(db, default_store, backend, stage):
    first = await blobs.record(db, backend, default_store.id, await stage(b"same"))
    second = await blobs.record(db, backend, default_store.id, await stage(b"same"))

    assert second.id == first.id
    assert await db.scalar(select(func.count()).select_from(Blob)) == 1


async def test_recording_content_again_clears_the_unreferenced_mark(
    db, default_store, backend, stage
):
    blob = await blobs.record(db, backend, default_store.id, await stage(b"again"))
    blob.unreferenced_since = NOW
    await db.flush()

    await blobs.record(db, backend, default_store.id, await stage(b"again"))

    assert blob.unreferenced_since is None


async def test_record_replaces_a_file_that_went_missing(db, default_store, backend, stage):
    blob = await blobs.record(db, backend, default_store.id, await stage(b"fragile"))
    await backend.delete(blob.sha256)

    await blobs.record(db, backend, default_store.id, await stage(b"fragile"))

    assert await backend.exists(blob.sha256)


async def test_dereference_marks_only_blobs_no_asset_uses(db, default_store, backend, stage):
    used = await blobs.record(db, backend, default_store.id, await stage(b"used"))
    unused = await blobs.record(db, backend, default_store.id, await stage(b"unused"))
    await add_asset(db, default_store, used, "a.bin")

    await blobs.dereference(db, [used.id, unused.id], NOW)
    await db.refresh(used)
    await db.refresh(unused)

    assert used.unreferenced_since is None
    assert unused.unreferenced_since == NOW


async def test_dereference_with_nothing_to_do(db):
    await blobs.dereference(db, [], NOW)

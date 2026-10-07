import pytest

from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.storage import blob_stores, blobs


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def test_the_default_store_lives_under_the_data_directory(settings, default_store):
    assert blob_stores.root_of(settings, default_store) == settings.data_dir / "blobs" / "default"


async def test_describe_reports_usage(db, settings, default_store, backend, stage):
    await blobs.record(db, backend, default_store.id, await stage(b"12345"))
    await blobs.record(db, backend, default_store.id, await stage(b"1234567"))

    view = await blob_stores.describe(db, settings, default_store)

    assert (view.name, view.type, view.path) == ("default", "file", "default")
    assert (view.blob_count, view.total_bytes) == (2, 12)
    assert view.available_bytes > 0


async def test_create_defaults_the_path_to_the_name(db, settings):
    store = await blob_stores.create_blob_store(db, name="archive", type="file", path=None)

    assert store.config == {"path": "archive"}
    assert blob_stores.root_of(settings, store) == settings.data_dir / "blobs" / "archive"
    assert (await blob_stores.get_blob_store(db, "archive")).id == store.id


async def test_an_absolute_path_is_used_as_given(db, settings, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    store = await blob_stores.create_blob_store(
        db, name="big-disk", type="file", path=str(elsewhere)
    )

    assert blob_stores.root_of(settings, store) == elsewhere


async def test_a_duplicate_name_is_a_conflict(db):
    error = await error_of(
        blob_stores.create_blob_store(db, name="default", type="file", path=None)
    )
    assert (error.status_code, error.code) == (409, "conflict")


@pytest.mark.parametrize(
    ("type", "path"), [("s3", None), ("file", "../outside"), ("file", "a/../../b"), ("file", "")]
)
async def test_invalid_stores_are_rejected(db, type, path):
    error = await error_of(blob_stores.create_blob_store(db, name="new", type=type, path=path))
    assert (error.status_code, error.code) == (422, "validation_error")


async def test_list_is_paged_in_name_order(db, settings):
    await blob_stores.create_blob_store(db, name="archive", type="file", path=None)

    page, total = await blob_stores.list_blob_stores(db, settings, limit=1, offset=1)

    assert total == 2
    assert [view.name for view in page] == ["default"]


async def test_a_store_in_use_cannot_be_deleted(db, default_store):
    db.add(
        Repository(
            name="files",
            name_key="files",
            format="raw",
            type="hosted",
            blob_store_id=default_store.id,
        )
    )
    await db.flush()

    error = await error_of(blob_stores.delete_blob_store(db, default_store))

    assert (error.status_code, error.code) == (409, "in_use")


async def test_an_unused_store_is_deleted_with_its_blob_records(db, settings, stage):
    store = await blob_stores.create_blob_store(db, name="archive", type="file", path=None)
    await blobs.record(
        db, blob_stores.backend_for(settings, store), store.id, await stage(b"left behind")
    )

    await blob_stores.delete_blob_store(db, store)

    assert await blob_stores.get_blob_store(db, "archive") is None

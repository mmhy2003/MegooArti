import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import Asset, Repository
from megooarti.storage.models import Blob, BlobStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def create(db, name="files", **fields):
    fields.setdefault("format", "raw")
    fields.setdefault("type", "hosted")
    fields.setdefault("online", True)
    fields.setdefault("blob_store", "default")
    fields.setdefault("hosted", None)
    fields.setdefault("format_config", {})
    return await service.create_repository(db, name=name, **fields)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def test_create_a_hosted_repository(db):
    repository = await create(db)

    view = await service.describe(db, repository)

    assert view == service.RepositoryView(
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        url_path="/repository/files/",
        hosted={"deployment_policy": "allow_redeploy"},
        format_config={},
    )


async def test_names_are_unique_ignoring_case_but_looked_up_exactly(db):
    await create(db, "Files")

    assert (await error_of(create(db, "files"))).code == "conflict"
    assert await service.get_repository(db, "Files") is not None
    assert await service.get_repository(db, "files") is None


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"format": "cobol"}, "format"),
        ({"type": "proxy"}, "type"),
        ({"type": "group"}, "type"),
        ({"blob_store": "ghost"}, "blob_store"),
        ({"hosted": {"deployment_policy": "sometimes"}}, "hosted.deployment_policy"),
        ({"format_config": {"anything": 1}}, "format_config"),
    ],
)
async def test_invalid_repositories_are_rejected(db, override, field):
    error = await error_of(create(db, **override))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == field


async def test_update_changes_online_and_policy_only(db):
    repository = await create(db)

    await service.update_repository(
        db, repository, online=False, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    view = await service.describe(db, repository)
    assert (view.online, view.hosted) == (False, {"deployment_policy": "read_only"})
    assert (view.name, view.format, view.type, view.blob_store) == (
        "files",
        "raw",
        "hosted",
        "default",
    )


async def test_update_validates_like_create(db):
    repository = await create(db)

    error = await error_of(
        service.update_repository(
            db, repository, online=True, hosted={"deployment_policy": "no"}, format_config={}
        )
    )

    assert error.code == "validation_error"


async def test_delete_removes_content_and_marks_its_blobs_unreferenced(db):
    repository = await create(db)
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id,
        sha256="a" * 64,
        md5="b" * 32,
        sha1="c" * 40,
        sha512="d" * 128,
        size=1,
    )
    db.add(blob)
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
    await db.flush()

    await service.delete_repository(db, repository, NOW)
    await db.refresh(blob)

    assert await service.get_repository(db, "files") is None
    assert await db.scalar(select(Asset.id)) is None
    assert blob.unreferenced_since == NOW


async def test_list_is_paged_in_name_order(db):
    for name in ("zeta", "alpha", "Beta"):
        await create(db, name)

    page, total = await service.list_repositories(db, limit=2, offset=1)

    assert total == 3
    assert [view.name for view in page] == ["Beta", "zeta"]
    assert await db.scalar(select(Repository.name_key).where(Repository.name == "Beta")) == "beta"


async def test_a_repository_with_very_many_assets_can_be_deleted(db):
    repository = await create(db)
    store = await db.scalar(select(BlobStore))
    many = 33_000  # more than one statement may carry as arguments
    blob_ids = [uuid.uuid4() for _ in range(many)]
    await db.execute(
        insert(Blob),
        [
            {
                "id": blob_id,
                "blob_store_id": store.id,
                "sha256": f"{number:064x}",
                "md5": "b" * 32,
                "sha1": "c" * 40,
                "sha512": "d" * 128,
                "size": 1,
                "created_at": NOW,
            }
            for number, blob_id in enumerate(blob_ids)
        ],
    )
    await db.execute(
        insert(Asset),
        [
            {
                "id": uuid.uuid4(),
                "repository_id": repository.id,
                "path": f"file-{number}.bin",
                "blob_id": blob_id,
                "content_type": "application/octet-stream",
                "kind": "asset",
                "attributes": {},
                "created_by": "dana",
                "created_at": NOW,
                "updated_at": NOW,
            }
            for number, blob_id in enumerate(blob_ids)
        ],
    )

    await service.delete_repository(db, repository, NOW)

    assert await db.scalar(select(func.count()).select_from(Asset)) == 0
    unmarked = select(func.count()).select_from(Blob).where(Blob.unreferenced_since.is_(None))
    assert await db.scalar(unmarked) == 0

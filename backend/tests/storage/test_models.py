from sqlalchemy import select

from megooarti.repositories.models import Asset, Component, Repository
from megooarti.storage.models import Blob, BlobStore


async def test_the_default_blob_store_exists(db):
    store = await db.scalar(select(BlobStore).where(BlobStore.name == "default"))

    assert (store.type, store.config) == ("file", {"path": "default"})


async def test_a_repository_with_a_component_an_asset_and_a_blob(db):
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id,
        sha256="a" * 64,
        md5="b" * 32,
        sha1="c" * 40,
        sha512="d" * 128,
        size=3,
    )
    repository = Repository(
        name="Files", name_key="files", format="raw", type="hosted", blob_store_id=store.id
    )
    db.add_all([blob, repository])
    await db.flush()
    component = Component(repository_id=repository.id, namespace="docs", name="a.txt")
    db.add(component)
    await db.flush()
    asset = Asset(
        repository_id=repository.id,
        component_id=component.id,
        path="docs/a.txt",
        blob_id=blob.id,
        content_type="text/plain",
        created_by="dana",
    )
    db.add(asset)
    await db.flush()

    assert (repository.online, repository.config) == (True, {})
    assert (component.version, component.attributes) == ("", {})
    assert (asset.kind, asset.attributes) == ("asset", {})
    assert asset.created_at is not None
    assert asset.updated_at is not None
    assert (asset.last_downloaded_at, asset.last_verified_at) == (None, None)
    assert (blob.created_at is not None, blob.unreferenced_since) == (True, None)


async def test_noting_a_download_does_not_change_when_the_asset_was_updated(db):
    store = await db.scalar(select(BlobStore))
    blob = Blob(
        blob_store_id=store.id,
        sha256="e" * 64,
        md5="b" * 32,
        sha1="c" * 40,
        sha512="d" * 128,
        size=1,
    )
    repository = Repository(
        name="files", name_key="files", format="raw", type="hosted", blob_store_id=store.id
    )
    db.add_all([blob, repository])
    await db.flush()
    asset = Asset(
        repository_id=repository.id,
        path="a.txt",
        blob_id=blob.id,
        content_type="text/plain",
        created_by="dana",
    )
    db.add(asset)
    await db.flush()
    updated = asset.updated_at

    asset.last_downloaded_at = asset.created_at
    await db.flush()

    assert asset.updated_at == updated

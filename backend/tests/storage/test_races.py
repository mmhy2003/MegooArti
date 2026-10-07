"""Behaviour that only real, concurrent transactions can show.

The other tests share one connection. These are synchronous, migrate their own
database, and drive their own event loop, like the migration tests.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

from alembic import command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.config import Settings
from megooarti.db.schema import alembic_config
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import ComponentKey, Format, get_format
from megooarti.repositories.models import Asset, Component, Repository
from megooarti.storage import blobs
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore
from tests.repositories.conftest import body, someone

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
Factory = async_sessionmaker[AsyncSession]


def run(database_url: str, tmp_path, scenario: Callable[[Factory, Settings], Awaitable[None]]):
    command.upgrade(alembic_config(database_url), "head")
    settings = Settings(_env_file=None, database_url=database_url, data_dir=tmp_path)

    async def main() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            await scenario(async_sessionmaker(engine, expire_on_commit=False), settings)
        finally:
            await engine.dispose()

    asyncio.run(main())


async def create_files(factory: Factory) -> tuple[Repository, BlobStore]:
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="files",
            format="raw",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        store = await db.get(BlobStore, repository.blob_store_id)
        await db.commit()
        return repository, store


def test_compaction_waits_for_an_upload_of_the_same_content(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, store = await create_files(factory)
        backend = backend_for(settings, store)

        async def staged():
            return await backend.stage(body(b"shared content"))

        async with factory() as db:
            blob = await blobs.record(db, backend, store.id, await staged())
            blob.unreferenced_since = NOW - timedelta(days=2)
            await db.commit()

        async with factory() as uploading:
            again = await blobs.record(uploading, backend, store.id, await staged())
            compaction = asyncio.create_task(
                blobs.compact(factory, settings, now=NOW, grace_seconds=3600)
            )
            finished, _ = await asyncio.wait({compaction}, timeout=1)
            assert not finished, "compaction did not wait for the upload being recorded"
            uploading.add(
                Asset(
                    repository_id=repository.id,
                    path="a.bin",
                    blob_id=again.id,
                    content_type="application/octet-stream",
                    created_by="dana",
                )
            )
            await uploading.commit()

        assert await asyncio.wait_for(compaction, timeout=30) == 0
        assert await backend.exists(again.sha256)
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(Blob)) == 1
            assert await db.scalar(select(Blob.unreferenced_since)) is None

    run(empty_database, tmp_path, scenario)


def test_two_writers_of_one_new_path_create_once_and_replace_once(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, store = await create_files(factory)

        async def chunks(data: bytes) -> AsyncIterator[bytes]:
            yield data

        async def write(data: bytes) -> bool:
            async with factory() as db:
                context = RepositoryContext(
                    db=db,
                    settings=settings,
                    repository=await db.get(Repository, repository.id),
                    principal=someone("*"),
                    format=get_format("raw"),
                    backend=backend_for(settings, store),
                )
                _, created = await context.put("same/path.bin", chunks(data))
                await db.commit()
                return created

        results = await asyncio.gather(write(b"first writer"), write(b"second writer"))

        assert sorted(results) == [False, True]
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(Asset)) == 1
            assert await db.scalar(select(func.count()).select_from(Blob)) == 2
            marked = await db.scalar(
                select(func.count()).select_from(Blob).where(Blob.unreferenced_since.is_not(None))
            )
            assert marked == 1

    run(empty_database, tmp_path, scenario)


class PackagePerDirectory(Format):
    """A format whose component spans every file in a directory, as real formats do."""

    name = "test-package"

    def describe_component(self, path: str) -> ComponentKey:
        return ComponentKey(namespace="", name=path.rpartition("/")[0])


def test_deleting_one_file_does_not_remove_a_sibling_being_uploaded(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, store = await create_files(factory)

        def context(db: AsyncSession) -> RepositoryContext:
            return RepositoryContext(
                db=db,
                settings=settings,
                repository=repository,
                principal=someone("*"),
                format=PackagePerDirectory(),
                backend=backend_for(settings, store),
            )

        async with factory() as db:
            await context(db).put("pkg/a.pom", body(b"descriptor"))
            await db.commit()

        async def delete_descriptor() -> bool:
            async with factory() as db:
                deleted = await context(db).delete("pkg/a.pom")
                await db.commit()
                return deleted

        async with factory() as uploading:
            await context(uploading).put("pkg/a.jar", body(b"archive"))
            deleting = asyncio.create_task(delete_descriptor())
            await asyncio.wait({deleting}, timeout=1)
            await uploading.commit()

        assert await asyncio.wait_for(deleting, timeout=30) is True
        async with factory() as db:
            assert list(await db.scalars(select(Asset.path))) == ["pkg/a.jar"]
            assert await db.scalar(select(func.count()).select_from(Component)) == 1

    run(empty_database, tmp_path, scenario)

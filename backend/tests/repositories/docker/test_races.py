"""A push and a delete at the same moment, which only real transactions can show."""

import asyncio

import pytest
from starlette.requests import Request

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.docker import names
from megooarti.repositories.docker.errors import RegistryError
from megooarti.repositories.docker.format import _manifest
from megooarti.repositories.docker.manifests import OCI_MANIFEST
from megooarti.repositories.models import Repository
from tests.repositories.conftest import someone
from tests.repositories.docker.conftest import digest_of, image_manifest, layer
from tests.storage.test_races import Factory, run

PUSHER = someone("repository:docker:images")
SHARED = layer("shared by both images")
OLD = image_manifest(b'{"image": "old"}', SHARED)
NEW = image_manifest(b'{"image": "new"}', SHARED)


def request(method: str, body: bytes = b"") -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    headers = [(b"content-type", OCI_MANIFEST.encode())]
    scope = {"type": "http", "method": method, "path": "/", "query_string": b"", "headers": headers}
    return Request(scope, receive)


async def context_in(db, settings: Settings, repository: Repository) -> RepositoryContext:
    return await build_context(db, settings, repository, PUSHER)


async def prepare(factory: Factory, settings: Settings) -> Repository:
    """A repository with the old image pushed, and the new one's blobs but not its manifest."""
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="images",
            format="docker",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        await db.commit()
        context = await context_in(db, settings, repository)
        for data in (SHARED, b'{"image": "old"}', b'{"image": "new"}'):
            await context.store(names.blob_path(digest_of(data)), await context.stage_bytes(data))
        await db.commit()
        await push(context, "old", OLD)
        await db.commit()
        return repository


async def push(context: RepositoryContext, image: str, manifest: bytes) -> None:
    parsed = names.DockerPath("manifest", image, "latest")
    await _manifest(context, request("PUT", manifest), parsed)


async def delete(context: RepositoryContext, image: str, manifest: bytes) -> None:
    parsed = names.DockerPath("manifest", image, digest_of(manifest))
    await _manifest(context, request("DELETE"), parsed)


async def state(factory: Factory, settings: Settings, repository: Repository) -> set[str]:
    async with factory() as db:
        context = await context_in(db, settings, repository)
        asked = [
            names.blob_path(digest_of(SHARED)),
            names.manifest_path("new", digest_of(NEW)),
            names.manifest_path("old", digest_of(OLD)),
        ]
        return {
            path.split("/")[0] + ":" + path.split("/")[1][:3]
            for path in await context.present(asked)
        }


def test_a_push_that_comes_first_keeps_the_layer_a_delete_would_have_removed(
    empty_database, tmp_path
):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await prepare(factory, settings)

        async def pushing() -> None:
            async with factory() as db:
                await push(await context_in(db, settings, repository), "new", NEW)
                await asyncio.sleep(0.3)  # stay open while the delete arrives
                await db.commit()

        async def deleting() -> None:
            await asyncio.sleep(0.1)
            async with factory() as db:
                await delete(await context_in(db, settings, repository), "old", OLD)
                await db.commit()

        await asyncio.gather(pushing(), deleting())

        assert await state(factory, settings, repository) == {"blobs:sha", "manifests:new"}

    run(empty_database, tmp_path, scenario)


def test_a_push_that_comes_second_is_refused_and_refers_to_nothing_missing(
    empty_database, tmp_path
):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await prepare(factory, settings)
        refused = []

        async def deleting() -> None:
            async with factory() as db:
                await delete(await context_in(db, settings, repository), "old", OLD)
                await asyncio.sleep(0.3)  # stay open while the push arrives
                await db.commit()

        async def pushing() -> None:
            await asyncio.sleep(0.1)
            async with factory() as db:
                with pytest.raises(RegistryError) as error:
                    await push(await context_in(db, settings, repository), "new", NEW)
                refused.append(error.value.code)

        await asyncio.gather(deleting(), pushing())

        assert refused == ["MANIFEST_BLOB_UNKNOWN"]
        assert await state(factory, settings, repository) == set()

    run(empty_database, tmp_path, scenario)

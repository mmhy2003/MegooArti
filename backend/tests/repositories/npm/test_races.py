"""Changes at the same moment, which only real, concurrent transactions can show."""

import asyncio
import json

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Repository
from megooarti.repositories.npm import documents, paths
from megooarti.repositories.npm.format import TAGS_LIMIT, _change_tags, _publish
from tests.repositories.conftest import someone
from tests.repositories.npm.conftest import publish_body
from tests.storage.test_races import Factory, run

PUBLISHER = someone("repository:npm:npm")


async def create_registry(factory: Factory) -> Repository:
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="npm",
            format="npm",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        await db.commit()
        return repository


async def context_in(db, settings: Settings, repository: Repository) -> RepositoryContext:
    return await build_context(db, settings, repository, PUBLISHER)


def upload_of(version: str, tag: str) -> documents.Upload:
    body = json.dumps(publish_body("left-pad", version, tag=tag)).encode()
    return documents.read_upload("left-pad", body)


async def stored_tags(db, settings: Settings, repository: Repository) -> dict:
    context = await context_in(db, settings, repository)
    return json.loads(await context.read(paths.dist_tags_path("left-pad"), limit=TAGS_LIMIT))


def test_two_versions_published_at_once_are_both_there(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_registry(factory)

        async def publish(version: str, tag: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                await _publish(context, "left-pad", upload_of(version, tag))
                await asyncio.sleep(0.2)  # stay open while the other publish happens
                await db.commit()

        await asyncio.gather(publish("1.0.0", "latest"), publish("2.0.0-beta.1", "beta"))

        async with factory() as db:
            context = await context_in(db, settings, repository)
            held = {info.version for info in await context.components("", "left-pad")}
            assert held == {"1.0.0", "2.0.0-beta.1"}
            assert await stored_tags(db, settings, repository) == {
                "latest": "1.0.0",
                "beta": "2.0.0-beta.1",
            }

    run(empty_database, tmp_path, scenario)


def test_two_tag_changes_at_once_are_both_kept(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_registry(factory)
        async with factory() as db:
            context = await context_in(db, settings, repository)
            await _publish(context, "left-pad", upload_of("1.0.0", "latest"))
            await db.commit()

        async def tag(name: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                await _change_tags(
                    context,
                    "left-pad",
                    lambda stored, held: documents.merge_tags(stored, {name: "1.0.0"}, held, held),
                )
                await asyncio.sleep(0.2)  # hold the lock while the other waits for it
                await db.commit()

        await asyncio.gather(tag("stable"), tag("lts"))

        async with factory() as db:
            assert await stored_tags(db, settings, repository) == {
                "latest": "1.0.0",
                "stable": "1.0.0",
                "lts": "1.0.0",
            }

    run(empty_database, tmp_path, scenario)

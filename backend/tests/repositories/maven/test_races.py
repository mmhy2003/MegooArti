"""Deploys at the same moment, which only real, concurrent transactions can show."""

import asyncio

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.format import STORED_LIMIT, keep_plugins
from megooarti.repositories.maven.metadata import Plugin
from megooarti.repositories.models import Repository
from tests.repositories.conftest import body, someone
from tests.storage.test_races import Factory, run

DEPLOYER = someone("repository:maven:releases")
GROUP = "com/acme/maven-metadata.xml"


async def create_releases(factory: Factory) -> Repository:
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="releases",
            format="maven",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        await db.commit()
        return repository


async def context_in(db, settings: Settings, repository: Repository) -> RepositoryContext:
    return await build_context(db, settings, repository, DEPLOYER)


def test_two_versions_deployed_at_once_are_both_listed(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_releases(factory)

        async def deploy(version: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                path = f"com/acme/app/{version}/app-{version}.jar"
                await context.put(path, body(version.encode()))
                await asyncio.sleep(0.2)  # stay open while the other deploy happens
                await db.commit()

        await asyncio.gather(deploy("1.0"), deploy("1.1"))

        async with factory() as db:
            context = await context_in(db, settings, repository)
            assert sorted(await context.versions("com.acme", "app")) == ["1.0", "1.1"]

    run(empty_database, tmp_path, scenario)


def test_two_plugin_prefix_uploads_at_once_are_both_kept(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_releases(factory)
        async with factory() as db:
            context = await context_in(db, settings, repository)
            for artifact in ("a-plugin", "b-plugin"):
                await context.put(f"com/acme/{artifact}/1.0/{artifact}-1.0.jar", body(b"x"))
            await db.commit()

        async def upload(artifact: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                plugin = Plugin(artifact, artifact[0], artifact)
                await keep_plugins(context, GROUP, "com.acme", (plugin,))
                await asyncio.sleep(0.2)  # hold the path lock while the other waits for it
                await db.commit()

        await asyncio.gather(upload("a-plugin"), upload("b-plugin"))

        async with factory() as db:
            context = await context_in(db, settings, repository)
            stored = metadata.parse(await context.read(GROUP, limit=STORED_LIMIT))
            assert {plugin.artifact_id for plugin in stored.plugins} == {"a-plugin", "b-plugin"}

    run(empty_database, tmp_path, scenario)

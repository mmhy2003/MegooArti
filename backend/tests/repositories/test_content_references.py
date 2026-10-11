import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Asset, AssetReference
from megooarti.storage.models import Blob
from tests.repositories.conftest import someone
from tests.storage.test_races import Factory, run

EVERYTHING = someone("repository:raw:files")


@pytest.fixture
async def context(files, context_for):
    return await context_for(files, EVERYTHING)


async def store(context, path: str, content: bytes = b"x", **options):
    staged = await context.stage_bytes(content)
    return await context.store(path, staged, **options)


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def make_old(db, *paths: str) -> None:
    long_ago = utcnow() - timedelta(days=3)
    await db.execute(update(Asset).where(Asset.path.in_(paths)).values(updated_at=long_ago))


async def test_a_file_records_what_it_refers_to(context):
    await store(context, "layers/a")
    await store(context, "layers/b")
    await store(context, "images/one", references=["layers/b", "layers/a", "layers/a"])

    assert await context.references("images/one") == ["layers/a", "layers/b"]
    assert await context.references("layers/a") == []
    assert await context.references("nothing/here") == []


async def test_storing_again_replaces_what_was_recorded_unless_nothing_is_said(context):
    await store(context, "images/one", references=["layers/a", "layers/b"])

    await store(context, "images/one", b"again")
    kept = await context.references("images/one")
    await store(context, "images/one", b"third", references=["layers/c"])
    replaced = await context.references("images/one")
    await store(context, "images/one", b"fourth", references=[])

    assert (kept, replaced) == (["layers/a", "layers/b"], ["layers/c"])
    assert await context.references("images/one") == []


async def test_which_paths_are_still_referred_to(context):
    await store(context, "images/one", references=["layers/a", "layers/b"])
    await store(context, "images/two", references=["layers/b", "layers/c"])

    asked = ["layers/a", "layers/b", "layers/c", "layers/d"]
    before = await context.referenced(asked)
    await context.delete("images/one")
    after = await context.referenced(asked)

    assert before == {"layers/a", "layers/b", "layers/c"}
    assert after == {"layers/b", "layers/c"}  # deleting a file forgets what it referred to
    assert await context.referenced([]) == set()


async def test_which_paths_have_a_file(context):
    await store(context, "layers/a")
    await store(context, "layers/b")

    assert await context.present(["layers/a", "layers/b", "layers/c"]) == {"layers/a", "layers/b"}
    assert await context.present([]) == set()


async def test_references_are_those_of_one_repository(context, context_for, db):
    other = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    elsewhere = await context_for(other, someone("repository:raw:more"))
    await store(context, "layers/a")
    await store(elsewhere, "images/one", references=["layers/a"])

    assert await context.referenced(["layers/a"]) == set()
    assert await elsewhere.referenced(["layers/a"]) == {"layers/a"}
    assert await context.references("images/one") == []
    assert await elsewhere.present(["layers/a"]) == set()


async def test_what_nothing_refers_to_can_be_found_once_it_is_old(context, db):
    for path in ("layers/used", "layers/unused", "layers/new", "layers/100%_odd", "other/unused"):
        await store(context, path)
    await store(context, "images/one", references=["layers/used"])
    await make_old(db, "layers/used", "layers/unused", "layers/100%_odd", "other/unused")
    a_day_ago = utcnow() - timedelta(days=1)

    found = await context.unreferenced("layers/", before=a_day_ago, limit=10)
    one = await context.unreferenced("layers/", before=a_day_ago, limit=1)
    literal = await context.unreferenced("layers/100%_", before=a_day_ago, limit=10)
    wildcard = await context.unreferenced("layers/1__%", before=a_day_ago, limit=10)

    assert found == ["layers/100%_odd", "layers/unused"]
    assert one == ["layers/100%_odd"]
    assert (literal, wildcard) == (["layers/100%_odd"], [])  # the prefix is taken literally


async def test_maintenance_removes_a_file_without_asking_who(files, context_for, db):
    writer = await context_for(files, EVERYTHING)
    await store(writer, "layers/a", b"content")
    nobody = await context_for(files, None)

    with pytest.raises(ApiError) as refused:
        await nobody.delete("layers/a")
    removed = await nobody.sweep("layers/a")
    again = await nobody.sweep("layers/a")

    assert refused.value.status_code == 401
    assert (removed, again) == (True, False)
    assert await count(db, Asset) == 0
    assert await db.scalar(select(Blob.unreferenced_since)) is not None  # left for compaction


async def test_sweeping_a_read_only_repository_still_works(db, context_for):
    frozen = await service.create_repository(
        db, name="frozen", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    writer = await context_for(frozen, someone("repository:raw:frozen"))
    await store(writer, "layers/a")
    await service.update_repository(
        db, frozen, online=True, hosted={"deployment_policy": "read_only"}
    )
    await db.commit()

    assert await (await context_for(frozen, None)).sweep("layers/a") is True


async def test_deleting_a_file_removes_its_references_with_it(context, db):
    await store(context, "images/one", references=["layers/a", "layers/b"])

    await context.delete("images/one")

    assert await count(db, AssetReference) == 0


def test_a_named_lock_makes_two_transactions_take_turns(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        async with factory() as db:
            repository = await service.create_repository(
                db, name="files", format="raw", type="hosted", online=True, blob_store="default"
            )
            await db.commit()
        order = []

        async def work(name: str, pause: float) -> None:
            async with factory() as db:
                context = await build_context(db, settings, repository, EVERYTHING)
                await context.lock("references")
                order.append(f"{name} in")
                await asyncio.sleep(pause)
                order.append(f"{name} out")
                await db.commit()

        first = asyncio.create_task(work("first", 0.3))
        await asyncio.sleep(0.1)
        await work("second", 0)
        await first

        assert order == ["first in", "first out", "second in", "second out"]

    run(empty_database, tmp_path, scenario)

"""What a repository's policies select (spec 4.2, E2, P3): walked in pages of the
database, a component as old as its newest file, never downloaded counting from when it
was made."""

import uuid

from sqlalchemy import delete, select, update

from megooarti.cleanup import selection
from megooarti.cleanup.criteria import Criteria
from megooarti.clock import utcnow
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Asset, Component
from tests.cleanup.conftest import age, put


async def selected(db, settings, repository, policies, **options) -> list[str]:
    context = await build_context(db, settings, repository, None)
    found = [held async for held in selection.selected(context, policies, utcnow(), **options)]
    return [path for held in found for path in held.paths]


async def joined(db, path: str, into: str) -> None:
    """Make the file at `path` part of the component of the file at `into`."""
    target = await db.scalar(select(Asset.component_id).where(Asset.path == into))
    own = await db.scalar(select(Asset.component_id).where(Asset.path == path))
    await db.execute(update(Asset).where(Asset.path == path).values(component_id=target))
    await db.execute(delete(Component).where(Component.id == own))
    await db.commit()


async def test_a_component_is_as_old_as_its_newest_file(client, root, db, settings, files):
    await put(client, root, "lib/a.txt")
    await put(client, root, "lib/a.txt.sig")
    await joined(db, "lib/a.txt.sig", "lib/a.txt")
    await age(db, "lib/a.txt", written=40)
    await age(db, "lib/a.txt.sig", written=10)
    old = [Criteria(updated_days=30)]

    assert await selected(db, settings, files, old) == []

    await age(db, "lib/a.txt.sig", written=40)
    assert sorted(await selected(db, settings, files, old)) == ["lib/a.txt", "lib/a.txt.sig"]


async def test_never_downloaded_counts_from_when_it_was_made(client, root, db, settings, files):
    await put(client, root, "old.txt")
    await put(client, root, "new.txt")
    await age(db, "old.txt", made=100)
    await age(db, "new.txt", made=10)

    found = await selected(db, settings, files, [Criteria(downloaded_days=90)])

    assert found == ["old.txt"]


async def test_a_download_keeps_a_component(client, root, db, settings, files):
    await put(client, root, "used.txt")
    await age(db, "used.txt", made=100, downloaded=2)

    assert await selected(db, settings, files, [Criteria(downloaded_days=90)]) == []


async def test_any_policy_selects(client, root, db, settings, files):
    await put(client, root, "old.txt")
    await put(client, root, "tmp/x.txt")
    await put(client, root, "kept.txt")
    await age(db, "old.txt", written=40)
    policies = [Criteria(updated_days=30), Criteria(asset_pattern=r"/tmp/.*")]

    found = await selected(db, settings, files, policies)

    assert sorted(found) == ["old.txt", "tmp/x.txt"]


async def test_a_component_with_no_files_does_not_end_the_walk(client, root, db, settings, files):
    # Left so by a rebuild of the index cut short: the first page holds it alone.
    db.add(Component(id=uuid.UUID(int=0), repository_id=files.id, namespace="", name="empty"))
    await db.commit()
    paths = [f"old/{number}.txt" for number in range(3)]
    for path in paths:
        await put(client, root, path)
        await age(db, path, written=40)

    found = await selected(db, settings, files, [Criteria(asset_pattern=".*")], batch=1)

    assert sorted(found) == paths


async def test_the_preview_walks_a_repository_in_pages(client, root, db, settings, files):
    paths = [f"old/{number}.txt" for number in range(5)]
    for path in paths:
        await put(client, root, path)
        await age(db, path, written=40)

    found = await selected(db, settings, files, [Criteria(updated_days=30)], batch=2)

    assert sorted(found) == paths

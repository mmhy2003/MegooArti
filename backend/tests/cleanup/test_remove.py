"""Removing one component as a run does (spec 5.2, E4, E6): every file of it, checked
again against the policies as they are first, in a read-only repository too."""

from sqlalchemy import delete, update

from megooarti.cleanup import run
from megooarti.cleanup.models import CleanupPolicy, RepositoryCleanupPolicy
from megooarti.clock import utcnow
from megooarti.repositories import service
from megooarti.repositories.models import Asset
from tests.cleanup.conftest import age, attach, component_id, paths_of, put


async def removing(db, settings, repository, path: str) -> str | None:
    found = await component_id(db, repository, path.rpartition("/")[2], "")
    context = await run.unattended_context(db, settings, repository)
    removed = await run.remove(context, found, utcnow())
    await db.commit()
    return removed


async def test_a_selected_component_goes_with_every_file(client, root, db, settings, files):
    await put(client, root, "lib/a.txt")
    await put(client, root, "lib/b.txt")
    await age(db, "lib/a.txt", written=40)
    await attach(db, files)

    removed = await removing(db, settings, files, "lib/a.txt")

    assert removed == "old"
    assert await paths_of(db, files) == ["lib/b.txt"]
    assert (await client.get("/repository/files/lib/a.txt", headers=root)).status_code == 404


async def test_a_component_used_since_it_was_picked_is_kept(client, root, db, settings, files):
    await put(client, root, "a.txt")
    await age(db, "a.txt", made=40)
    policy = await attach(db, files, downloaded_days=30)
    assert policy.downloaded_days == 30
    await db.execute(update(Asset).where(Asset.path == "a.txt").values(last_downloaded_at=utcnow()))
    await db.commit()

    assert await removing(db, settings, files, "a.txt") is None
    assert await paths_of(db, files) == ["a.txt"]


async def test_a_policy_detached_meanwhile_removes_no_more(client, root, db, settings, files):
    await put(client, root, "a.txt")
    await age(db, "a.txt", written=40)
    await attach(db, files)
    await db.execute(delete(RepositoryCleanupPolicy))
    await db.commit()

    assert await removing(db, settings, files, "a.txt") is None
    assert await paths_of(db, files) == ["a.txt"]


async def test_a_policy_changed_meanwhile_decides(client, root, db, settings, files):
    await put(client, root, "a.txt")
    await age(db, "a.txt", written=40)
    await attach(db, files)
    await db.execute(update(CleanupPolicy).values(updated_days=90))
    await db.commit()

    assert await removing(db, settings, files, "a.txt") is None


async def test_a_read_only_repository_is_cleaned(client, root, db, settings, files):
    await put(client, root, "a.txt")
    await age(db, "a.txt", written=40)
    await attach(db, files)
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "read_only"}
    )
    await db.commit()

    assert await removing(db, settings, files, "a.txt") == "old"
    assert await paths_of(db, files) == []

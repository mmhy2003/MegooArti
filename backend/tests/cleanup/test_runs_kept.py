"""A repository's last cleanup run (spec 5.1, R5): kept one for each repository, shown with
it, not part of what its records say changed, and gone with it."""

from sqlalchemy import select

from megooarti.cleanup.models import CleanupRun
from megooarti.clock import utcnow
from megooarti.repositories import service
from tests.audit import last

REPOSITORIES = "/api/v1/repositories"


async def test_a_repository_shows_its_last_run(admin_client, db, files):
    before = (await admin_client.get(f"{REPOSITORIES}/files")).json()
    now = utcnow()
    db.add(
        CleanupRun(
            repository_id=files.id, started_at=now, finished_at=now, removed=3, failed=1, by="root"
        )
    )
    await db.commit()

    after = (await admin_client.get(f"{REPOSITORIES}/files")).json()

    assert before["cleanup"] is None
    assert after["cleanup"]["removed"] == 3
    assert after["cleanup"]["failed"] == 1
    assert after["cleanup"]["by"] == "root"
    assert after["cleanup"]["error"] is None
    assert after["cleanup"]["finished_at"] is not None


async def test_the_last_run_is_not_a_change_of_settings(admin_client, db, sessionmaker, files):
    now = utcnow()
    db.add(CleanupRun(repository_id=files.id, started_at=now, finished_at=now))
    await db.commit()

    await admin_client.put(f"{REPOSITORIES}/files", json={"online": False})

    record = await last(sessionmaker, "repository.updated")
    assert "cleanup" not in record.changes


async def test_the_last_run_goes_with_its_repository(db, files):
    db.add(CleanupRun(repository_id=files.id, started_at=utcnow()))
    await db.commit()

    await service.delete_repository(db, files, utcnow())
    await db.commit()

    assert list(await db.scalars(select(CleanupRun))) == []

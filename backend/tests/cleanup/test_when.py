"""When repositories are cleaned (spec 5.1, E5): checked hourly, each a day after its own
last run finished, by one container at a time; not at all with an interval of nought."""

import asyncio
from datetime import timedelta

from megooarti import main
from megooarti.cleanup import run
from megooarti.cleanup.models import CleanupRun
from megooarti.clock import utcnow
from megooarti.main import create_app
from tests.cleanup.conftest import age, attach, paths_of, put
from tests.clients import client_for

DAY = 86400


async def ran(db, repository, *, hours_ago: float, finished: bool = True) -> None:
    when = utcnow() - timedelta(hours=hours_ago)
    kept = await db.get(CleanupRun, repository.id) or CleanupRun(repository_id=repository.id)
    kept.started_at = when
    kept.finished_at = when if finished else None
    db.add(kept)
    await db.commit()


async def test_a_repository_is_due_a_day_after_its_last_run(client, root, db, files):
    from tests.repositories.test_content_api import create

    await attach(db, files)
    group = await create(db, "all", type="group", group={"members": ["files"]})
    await create(db, "bare")
    assert group is not None

    assert await run.due(db, utcnow(), DAY) == [files.id]  # never run
    await ran(db, files, hours_ago=2)
    assert await run.due(db, utcnow(), DAY) == []
    assert await run.due(db, utcnow(), 3600) == [files.id]
    await ran(db, files, hours_ago=25)
    assert await run.due(db, utcnow(), DAY) == [files.id]
    await ran(db, files, hours_ago=25, finished=False)  # cut short
    assert await run.due(db, utcnow(), DAY) == [files.id]


async def test_a_run_cut_short_is_due_at_the_next_check(db, files):
    # Stopped by a restart an hour ago: taken up again, not a day after it began (R10).
    await attach(db, files)
    await ran(db, files, hours_ago=1, finished=False)

    assert await run.due(db, utcnow(), DAY) == [files.id]


async def test_a_repository_cleaned_meanwhile_is_not_cleaned_again(
    app, client, root, db, files, monkeypatch
):
    # Due when the list was made; cleaned by another run before its turn came.
    await put(client, root, "old.txt")
    await age(db, "old.txt", written=40)
    await attach(db, files)
    await ran(db, files, hours_ago=0)
    kept = await db.get(CleanupRun, files.id)
    finished = kept.finished_at

    async def stale(db, now, interval_seconds):
        return [files.id]

    monkeypatch.setattr(run, "due", stale)

    assert await run.daily(app) == 0
    again = await db.get(CleanupRun, files.id, populate_existing=True)
    assert again.finished_at == finished
    assert await paths_of(db, files) == ["old.txt"]


async def test_the_daily_check_cleans_what_is_due(app, client, root, db, files):
    await put(client, root, "old.txt")
    await age(db, "old.txt", written=40)
    await attach(db, files)

    assert await run.daily(app) == 1
    assert await paths_of(db, files) == []
    assert await db.get(CleanupRun, files.id, populate_existing=True) is not None


async def test_a_restart_does_not_push_the_run_back(
    settings, sessionmaker, make_user, db, files, monkeypatch
):
    await attach(db, files)
    await ran(db, files, hours_ago=25)
    monkeypatch.setattr(run, "CHECK_SECONDS", 0.05)
    app = create_app(settings)
    app.state.sessionmaker = sessionmaker

    async with client_for(app):
        for _ in range(100):
            kept = await db.get(CleanupRun, files.id, populate_existing=True)
            if kept.started_at > utcnow() - timedelta(hours=1):
                break
            await asyncio.sleep(0.05)

    assert kept.started_at > utcnow() - timedelta(hours=1)


async def test_an_interval_of_nought_turns_the_daily_run_off(settings, sessionmaker, monkeypatch):
    names: list[str] = []
    real = main.run_periodically

    def recorded(name, interval, job):
        names.append(name)
        return real(name, interval, job)

    monkeypatch.setattr(main, "run_periodically", recorded)
    for interval in (0, DAY):
        app = create_app(settings.model_copy(update={"cleanup_interval_seconds": interval}))
        app.state.sessionmaker = sessionmaker
        async with client_for(app):
            pass

    assert names.count("cleanup") == 1

"""The run of one repository (spec 5.2, E11, E12): what its policies select removed a
transaction at a time, its run kept and recorded once, a failure passed over, a run cut
short taken up again, one run of a repository at a time."""

import asyncio

import pytest
import structlog
from sqlalchemy import select

from megooarti.cleanup import run
from megooarti.cleanup.models import CleanupRun
from megooarti.repositories.formats import get_format
from tests.audit import last
from tests.cleanup.conftest import age, attach, paths_of, put

OLD = [f"old/{number}.txt" for number in range(5)]
NEW = ["new/a.txt", "new/b.txt"]


async def stored(client, root, db, files) -> None:
    for path in OLD + NEW:
        await put(client, root, path)
    for path in OLD:
        await age(db, path, written=40)
    await attach(db, files)


async def the_run(db, files) -> CleanupRun:
    found = await db.get(CleanupRun, files.id, populate_existing=True)
    assert found is not None
    return found


async def test_a_run_removes_what_the_policies_select_and_says_so(
    client, root, db, sessionmaker, settings, files
):
    await stored(client, root, db, files)

    with structlog.testing.capture_logs() as logs:
        await run.clean(sessionmaker, settings, files.id, batch=2)

    assert await paths_of(db, files) == sorted(NEW)
    kept = await the_run(db, files)
    assert (kept.removed, kept.failed, kept.by, kept.error) == (5, 0, None, None)
    assert kept.finished_at is not None
    record = await last(sessionmaker, "repository.cleaned_up")
    assert record.target_name == "files"
    assert record.changes == {
        "removed": {"before": None, "after": 5},
        "policies": {"before": None, "after": ["old"]},
    }
    assert record.method == "system"
    (finished,) = [entry for entry in logs if entry["event"] == "cleanup_finished"]
    assert (finished["repository"], finished["removed"]) == ("files", 5)
    assert "seconds" in finished


async def test_one_component_that_fails_does_not_stop_the_others(
    client, root, db, sessionmaker, settings, files, monkeypatch
):
    await stored(client, root, db, files)
    raw = get_format("raw")
    original = raw.cleaned_up

    async def failing(context, removed):
        if any(path == "old/2.txt" for path, _ in removed):
            raise RuntimeError("this one cannot go")
        await original(context, removed)

    monkeypatch.setattr(raw, "cleaned_up", failing)

    with structlog.testing.capture_logs() as logs:
        await run.clean(sessionmaker, settings, files.id)

    assert await paths_of(db, files) == sorted(["old/2.txt", *NEW])
    kept = await the_run(db, files)
    assert (kept.removed, kept.failed) == (4, 1)
    assert [entry["event"] for entry in logs].count("cleanup_component_failed") == 1


async def test_a_run_cut_short_is_run_again(
    client, root, db, sessionmaker, settings, files, monkeypatch
):
    await stored(client, root, db, files)
    original = run.remove
    calls = 0

    async def stopping(context, component_id, now):
        nonlocal calls
        calls += 1
        if calls > 2:
            raise asyncio.CancelledError
        return await original(context, component_id, now)

    monkeypatch.setattr(run, "remove", stopping)
    with pytest.raises(asyncio.CancelledError):
        await run.clean(sessionmaker, settings, files.id)

    assert len(await paths_of(db, files)) == len(OLD + NEW) - 2
    assert (await the_run(db, files)).finished_at is None

    monkeypatch.setattr(run, "remove", original)
    await run.clean(sessionmaker, settings, files.id)
    assert await paths_of(db, files) == sorted(NEW)


async def test_the_preview_says_what_the_run_removes(
    client, root, db, sessionmaker, settings, files
):
    await stored(client, root, db, files)
    previewed = await client.post(
        "/api/v1/cleanup-policies/preview",
        json={"format": "raw", "updated_days": 30, "repository": "files"},
        headers=root,
    )
    named = {item["name"] for item in previewed.json()["items"]}

    await run.clean(sessionmaker, settings, files.id)

    assert named == {path.rpartition("/")[2] for path in OLD}
    assert await paths_of(db, files) == sorted(NEW)


async def test_a_repository_is_claimed_once(app, files, db):
    engine = app.state.engine
    other = await db.scalar(select(CleanupRun.repository_id))  # none: any other id will do
    assert other is None

    first = await run.claim(engine, files.id)
    second = await run.claim(engine, files.id)
    elsewhere = await run.claim(engine, run.uuid.uuid4())
    try:
        assert first is not None
        assert second is None
        assert elsewhere is not None
    finally:
        await run.release(first, files.id)
        if elsewhere is not None:
            await elsewhere.close()
    again = await run.claim(engine, files.id)
    assert again is not None
    await run.release(again, files.id)

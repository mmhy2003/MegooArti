"""Cleaning a repository up now (spec 5.1, R6 to R8): answered at once, run in the
server, one run of a repository at a time; and how many it would remove, counted once."""

import asyncio

from megooarti.cleanup import run
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.audit import last
from tests.cleanup.conftest import age, attach, paths_of, put

REPOSITORIES = "/api/v1/repositories"


async def aged_file(client, root, db, files) -> None:
    await put(client, root, "old.txt")
    await put(client, root, "new.txt")
    await age(db, "old.txt", written=40)


async def test_clean_up_now_answers_at_once_and_cleans(
    app, admin_client, db, sessionmaker, files, make_user
):
    await make_user("uploader", roles=["admin"])
    await aged_file(admin_client, basic("uploader", PASSWORD), db, files)
    await attach(db, files)

    started = await admin_client.post(f"{REPOSITORIES}/files/cleanup")
    await asyncio.gather(*app.state.cleanups)
    shown = (await admin_client.get(f"{REPOSITORIES}/files")).json()

    assert started.status_code == 202, started.text
    assert await paths_of(db, files) == ["new.txt"]
    assert (shown["cleanup"]["removed"], shown["cleanup"]["by"]) == (1, "root")
    assert (await last(sessionmaker, "repository.cleaned_up")).actor == "root"


async def test_a_repository_is_cleaned_by_one_run_at_a_time(app, admin_client, db, files):
    await attach(db, files)
    other = await admin_client.post(
        REPOSITORIES, json={"name": "other", "format": "raw", "type": "hosted"}
    )
    await admin_client.put(f"{REPOSITORIES}/other", json={"cleanup_policies": ["old"]})
    held = await run.claim(app.state.engine, files.id)
    try:
        busy = await admin_client.post(f"{REPOSITORIES}/files/cleanup")
        elsewhere = await admin_client.post(f"{REPOSITORIES}/other/cleanup")
        await asyncio.gather(*app.state.cleanups)
    finally:
        await run.release(held, files.id)

    assert other.status_code == 201
    assert (busy.status_code, error_code(busy)) == (409, "cleanup_running")
    assert elsewhere.status_code == 202


async def test_runs_started_now_are_few_at_a_time(app, admin_client, db, files, monkeypatch):
    # Each run holds connections for as long as it lasts: a few at once, not every one.
    monkeypatch.setattr(run, "MOST_AT_ONCE", 1)
    await attach(db, files)
    other = await admin_client.post(
        REPOSITORIES, json={"name": "other", "format": "raw", "type": "hosted"}
    )
    await admin_client.put(f"{REPOSITORIES}/other", json={"cleanup_policies": ["old"]})
    going = asyncio.Event()
    real = run.clean

    async def slow(*args, **kwargs):
        await going.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(run, "clean", slow)
    first = await admin_client.post(f"{REPOSITORIES}/files/cleanup")
    second = await admin_client.post(f"{REPOSITORIES}/other/cleanup")
    going.set()
    await asyncio.gather(*app.state.cleanups)
    third = await admin_client.post(f"{REPOSITORIES}/other/cleanup")
    await asyncio.gather(*app.state.cleanups)

    assert other.status_code == 201
    assert first.status_code == 202
    assert (second.status_code, error_code(second)) == (409, "cleanup_busy")
    assert third.status_code == 202


async def test_clean_up_now_needs_policies_and_a_repository_that_holds(admin_client, files):
    bare = await admin_client.post(f"{REPOSITORIES}/files/cleanup")
    await admin_client.post(
        REPOSITORIES,
        json={"name": "all", "format": "raw", "type": "group", "group": {"members": ["files"]}},
    )
    group = await admin_client.post(f"{REPOSITORIES}/all/cleanup")
    missing = await admin_client.post(f"{REPOSITORIES}/nowhere/cleanup")

    assert (bare.status_code, error_code(bare)) == (409, "no_cleanup_policies")
    assert (group.status_code, error_code(group)) == (409, "no_cleanup_policies")
    assert (missing.status_code, error_code(missing)) == (404, "not_found")


async def test_how_many_it_would_remove_is_counted_once(admin_client, make_user, db, files):
    await make_user("uploader", roles=["admin"])
    await aged_file(admin_client, basic("uploader", PASSWORD), db, files)
    await attach(db, files, "old")
    await attach(db, files, "older", updated_days=35)

    counted = await admin_client.post(f"{REPOSITORIES}/files/cleanup/preview")

    assert counted.status_code == 200, counted.text
    assert counted.json() == {"total": 1}
    assert await paths_of(db, files) == ["new.txt", "old.txt"]


async def test_running_and_counting_need_repositories_write(
    client, make_user, sessionmaker, db, files
):
    await attach(db, files)
    async with sessionmaker() as session:
        await roles.create_role(session, "readers", "", ["admin:repositories:read"], [])
        await session.commit()
    await make_user("rita", roles=["readers"])
    rita = basic("rita", PASSWORD)

    assert (await client.post(f"{REPOSITORIES}/files/cleanup", headers=rita)).status_code == 403
    counting = await client.post(f"{REPOSITORIES}/files/cleanup/preview", headers=rita)
    assert counting.status_code == 403

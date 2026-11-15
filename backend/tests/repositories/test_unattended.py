"""Deleting with nobody calling (cleanup spec 5.3, R1): the format's own effects, no
permission asked, the deployment policy ignored; and only the cleanup run does it."""

from pathlib import Path

import pytest

from megooarti.errors import ApiError
from megooarti.repositories import removal, service
from megooarti.repositories.content import build_context
from megooarti.repositories.npm import paths
from tests.accounts import PASSWORD, basic
from tests.repositories.npm.conftest import address, create, publish

SOURCE = Path(__file__).resolve().parents[2] / "src" / "megooarti"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def test_an_unattended_delete_runs_the_formats_effects(client, db, settings, root):
    registry = await create(db, "npm")
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "tool", version)
    context = await build_context(db, settings, registry, None, unattended=True)

    deleted = await removal.delete_file(context, paths.tarball_path("tool", "2.0.0"))
    await db.commit()
    document = (await client.get(address("tool"), headers=root)).json()

    assert deleted is True
    assert (list(document["versions"]), document["dist-tags"]) == (["1.0.0"], {"latest": "1.0.0"})


async def test_an_unattended_delete_ignores_read_only(client, db, settings, root, files):
    put = await client.put("/repository/files/a.txt", content=b"a", headers=root)
    assert put.status_code == 201
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "read_only"}
    )
    await db.commit()
    context = await build_context(db, settings, files, None, unattended=True)

    assert await removal.delete_file(context, "a.txt") is True


async def test_a_context_with_nobody_calling_still_deletes_nothing(
    client, db, settings, root, files
):
    put = await client.put("/repository/files/a.txt", content=b"a", headers=root)
    assert put.status_code == 201
    context = await build_context(db, settings, files, None)

    with pytest.raises(ApiError) as refused:
        await removal.delete_file(context, "a.txt")

    assert refused.value.status_code == 401


def test_only_the_run_deletes_unattended():
    passing = {
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if "unattended=True" in path.read_text(encoding="utf-8")
    }

    assert passing <= {"cleanup/run.py"}

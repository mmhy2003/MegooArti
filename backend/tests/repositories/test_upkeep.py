from datetime import timedelta

import structlog
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.repositories import formats, service, upkeep, uploads
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset, Upload
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import body, someone


class Tidy(Format):
    """A format that, as upkeep, removes what is under `scratch/`."""

    name = "raw"

    def __init__(self) -> None:
        self.tended: list[tuple[str, object]] = []

    async def maintain(self, context, now):
        self.tended.append((context.repository.name, context.principal))
        if context.repository.name == "broken":
            raise RuntimeError("this one cannot be tended")
        for path in await context.present(["scratch/a", "scratch/b"]):
            await context.sweep(path)


async def create(db, name: str):
    repository = await service.create_repository(
        db, name=name, format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    return repository


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_every_format_tends_its_repositories(
    db, sessionmaker, settings, context_for, monkeypatch
):
    tidy = Tidy()
    monkeypatch.setitem(formats._registry, "raw", tidy)
    for name in ("alpha", "broken", "gamma"):
        repository = await create(db, name)
        writer = await context_for(repository, someone(f"repository:raw:{name}"))
        await writer.put("scratch/a", body(b"left over"))
        await writer.put("kept/a", body(b"wanted"))
    await db.commit()

    with structlog.testing.capture_logs() as logs:
        await upkeep.run(sessionmaker, settings, utcnow())

    assert tidy.tended == [("alpha", None), ("broken", None), ("gamma", None)]
    kept = await db.scalars(select(Asset.path).order_by(Asset.path))
    assert list(kept) == ["kept/a", "kept/a", "kept/a", "scratch/a"]  # only broken's is left
    failed = [entry for entry in logs if entry["event"] == "upkeep_failed"]
    assert [entry["repository"] for entry in failed] == ["broken"]


async def test_the_generic_format_needs_no_upkeep(db, sessionmaker, settings, files, context_for):
    writer = await context_for(files, someone("repository:raw:files"))
    await writer.put("scratch/a", body(b"left alone"))
    await db.commit()

    await upkeep.run(sessionmaker, settings, utcnow())

    assert await count(db, Asset) == 1


async def test_uploads_that_were_left_are_removed(db, sessionmaker, settings, files, context_for):
    writer = await context_for(files, someone("repository:raw:files"))
    old = await uploads.begin(writer, "app")
    await uploads.begin(writer, "app")
    await db.execute(
        update(Upload)
        .where(Upload.id == uploads._identifier(old))
        .values(updated_at=utcnow() - timedelta(days=2))
    )
    await db.commit()

    await upkeep.run(sessionmaker, settings, utcnow())

    assert await count(db, Upload) == 1


class Elsewhere(Format):
    """A format whose repositories are reached through a protocol of their own."""

    name = "raw"
    served_at = "registry"


async def test_a_format_served_elsewhere_is_not_served_under_repository(
    client, files, make_user, monkeypatch
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    await client.put("/repository/files/a.txt", content=b"x", headers=root)
    monkeypatch.setitem(formats._registry, "raw", Elsewhere())

    read = await client.get("/repository/files/a.txt", headers=root)
    written = await client.put("/repository/files/b.txt", content=b"y", headers=root)
    without_credentials = await client.get("/repository/files/a.txt")
    unknown = await client.get("/repository/no-such-repository/a.txt")

    for response in (read, written, without_credentials):
        assert (response.status_code, error_code(response)) == (404, "not_found")
    # To someone who has not signed in, it looks like a repository that does not exist.
    assert without_credentials.status_code == unknown.status_code


def test_formats_are_served_under_repository_unless_they_say_otherwise():
    assert Format.served_at == "repository"
    assert all(
        formats.get_format(name).served_at == "repository"
        for name in ("raw", "maven", "npm", "pypi")
    )

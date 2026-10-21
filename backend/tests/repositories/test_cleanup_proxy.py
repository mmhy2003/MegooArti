"""A proxy's file removed by a cleanup run takes its companions (cleanup spec 7.2, R3):
its files of no component whose path is the removed file's and more."""

from sqlalchemy import select

from megooarti.cleanup import run
from megooarti.clock import utcnow
from megooarti.repositories.models import Asset
from tests.accounts import PASSWORD, basic
from tests.cleanup.conftest import age, attach, component_id, paths_of


async def test_a_proxys_companions_go_with_a_file(
    client, make_user, db, settings, mirror, fake_remote
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    fake_remote.files["files/tool.bin"] = b"a tool"
    fake_remote.files["files/other.bin"] = b"another"
    for path in ("tool.bin", "other.bin"):
        assert (await client.get(f"/repository/mirror/{path}", headers=root)).status_code == 200
    blob = await db.scalar(select(Asset.blob_id).where(Asset.path == "tool.bin"))
    for path in ("tool.bin.sha1", "other.bin.sha1"):
        db.add(
            Asset(
                repository_id=mirror.id,
                component_id=None,
                path=path,
                blob_id=blob,
                content_type="text/plain",
                created_by="proxy",
            )
        )
    await db.commit()
    await age(db, "tool.bin", written=40, repository="mirror")
    await attach(db, mirror)

    context = await run.unattended_context(db, settings, mirror)
    removed = await run.remove(context, await component_id(db, mirror, "tool.bin", ""), utcnow())
    await db.commit()

    assert removed == "old"
    assert await paths_of(db, mirror) == ["other.bin", "other.bin.sha1"]

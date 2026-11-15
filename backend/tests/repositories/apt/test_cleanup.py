"""A package removed by a cleanup run leaves the indexes (cleanup spec E4)."""

from megooarti.cleanup import run
from megooarti.clock import utcnow
from tests.cleanup.conftest import age_everything, attach, component_id
from tests.repositories.apt.conftest import URL, upload
from tests.repositories.apt.packages import make_deb

PACKAGES = f"{URL}/dists/stable/main/binary-amd64/Packages"


async def test_a_removed_package_leaves_the_index(client, root, db, settings, hosted):
    assert (await upload(client, root, make_deb())).status_code == 201
    before = await client.get(PACKAGES, headers=root)
    await age_everything(db, hosted, written=40)
    await attach(db, hosted)

    context = await run.unattended_context(db, settings, hosted)
    removed = await run.remove(
        context, await component_id(db, hosted, "megooarti-hello", "1.0-1"), utcnow()
    )
    await db.commit()
    after = await client.get(PACKAGES, headers=root)

    assert removed == "old"
    assert b"megooarti-hello" in before.content
    assert b"megooarti-hello" not in after.content

"""A version removed by a cleanup run leaves the package as `npm unpublish` would (cleanup
spec E4)."""

from sqlalchemy import update

from megooarti.cleanup import run
from megooarti.clock import utcnow
from megooarti.repositories.models import Asset
from megooarti.repositories.npm import paths
from tests.cleanup.conftest import attach, component_id, days_ago
from tests.repositories.npm.conftest import address, publish


async def test_a_removed_version_leaves_the_dist_tags_without_it(
    client, root, db, settings, registry
):
    for version in ("1.0.0", "2.0.0"):
        assert (await publish(client, root, "tool", version)).status_code == 201
    await db.execute(
        update(Asset)
        .where(Asset.path == paths.tarball_path("tool", "2.0.0"))
        .values(updated_at=days_ago(40))
    )
    await db.commit()
    await attach(db, registry)

    context = await run.unattended_context(db, settings, registry)
    removed = await run.remove(context, await component_id(db, registry, "tool", "2.0.0"), utcnow())
    await db.commit()
    document = (await client.get(address("tool"), headers=root)).json()

    assert removed == "old"
    assert (list(document["versions"]), document["dist-tags"]) == (["1.0.0"], {"latest": "1.0.0"})

"""A release a PyPI proxy cached, removed by a cleanup run, takes the metadata it cached
beside its file (cleanup spec 7.2, R3)."""

from megooarti.cleanup import run
from megooarti.clock import utcnow
from tests.cleanup.conftest import age_everything, attach, component_id, paths_of
from tests.repositories.pypi.test_proxy import PAGE, WHEEL_URL
from tests.repositories.pypi.test_proxy import remote as remote  # noqa: F401 (a fixture)


async def test_a_cached_release_takes_its_metadata(client, root, db, settings, upstream, remote):
    for address in (PAGE, WHEEL_URL, f"{WHEEL_URL}.metadata"):
        assert (await client.get(address, headers=root)).status_code == 200
    await age_everything(db, upstream, written=40)
    await attach(db, upstream)

    context = await run.unattended_context(db, settings, upstream)
    removed = await run.remove(
        context, await component_id(db, upstream, "requests", "2.31.0"), utcnow()
    )
    await db.commit()

    assert removed == "old"
    assert not [path for path in await paths_of(db, upstream) if "2.31.0" in path]

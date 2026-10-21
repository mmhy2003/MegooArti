"""A NuGet version removed by a cleanup run goes with its symbols (cleanup spec E4), as
deleting its package does."""

from megooarti.cleanup import run
from megooarti.clock import utcnow
from tests.cleanup.conftest import age_everything, attach, component_id, paths_of
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg, snupkg


async def test_a_removed_version_takes_its_symbols(client, root, db, settings, hosted):
    assert (await push(client, root, nupkg("MegooArti.Hello", "1.0.0"))).status_code == 201
    pushed = await push(client, root, snupkg("MegooArti.Hello", "1.0.0"), symbols=True)
    assert pushed.status_code == 201
    await age_everything(db, hosted, written=40)
    await attach(db, hosted)
    found = await component_id(db, hosted, "MegooArti.Hello", "1.0.0")

    context = await run.unattended_context(db, settings, hosted)
    removed = await run.remove(context, found, utcnow())
    await db.commit()

    assert removed == "old"
    assert not [path for path in await paths_of(db, hosted) if "1.0.0" in path or ".pdb" in path]

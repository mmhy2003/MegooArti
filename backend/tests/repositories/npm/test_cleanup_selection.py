"""A cleanup policy selects components, never the documents npm keeps of them (cleanup
spec E1): the dist-tags have no component."""

from megooarti.cleanup import selection
from megooarti.cleanup.criteria import Criteria
from megooarti.clock import utcnow
from megooarti.repositories.content import build_context
from tests.repositories.npm.conftest import publish


async def test_files_of_no_component_are_never_selected(client, root, db, settings, registry):
    assert (await publish(client, root, "left-pad", "1.0.0")).status_code == 201
    context = await build_context(db, settings, registry, None)

    found = [
        held async for held in selection.selected(context, [Criteria(asset_pattern=".*")], utcnow())
    ]

    assert [(held.name, held.version) for held in found] == [("left-pad", "1.0.0")]
    assert all(not path.endswith("dist-tags") for held in found for path in held.paths)

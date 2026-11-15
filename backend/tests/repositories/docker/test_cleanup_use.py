"""A tag is in use while the image it names is pulled, by its digest too (cleanup spec
7.3): "not downloaded" is the newest of the tag's and its manifest's."""

from datetime import timedelta

from sqlalchemy import update

from megooarti.cleanup import selection
from megooarti.cleanup.criteria import Criteria
from megooarti.clock import utcnow
from megooarti.repositories.content import build_context
from megooarti.repositories.docker import names
from megooarti.repositories.models import Asset, Component
from tests.repositories.docker.conftest import digest_of, push_image


async def selected(db, settings, repository) -> list[tuple[str, str, str]]:
    context = await build_context(db, settings, repository, None)
    policies = [Criteria(downloaded_days=30)]
    return [
        (held.namespace, held.name, held.version)
        async for held in selection.selected(context, policies, utcnow())
    ]


async def test_a_tag_is_used_while_its_manifest_is_pulled(client, root, db, settings, images):
    manifest = await push_image(client, root, "app", "1.0", "layer one")
    long_ago = utcnow() - timedelta(days=100)
    await db.execute(
        update(Asset).where(Asset.repository_id == images.id).values(last_downloaded_at=None)
    )
    await db.execute(
        update(Component).where(Component.repository_id == images.id).values(created_at=long_ago)
    )
    pulled = names.manifest_path("app", digest_of(manifest))
    await db.execute(
        update(Asset)
        .where(Asset.repository_id == images.id, Asset.path == pulled)
        .values(last_downloaded_at=utcnow() - timedelta(days=1))
    )
    await db.commit()

    assert await selected(db, settings, images) == []

    await db.execute(update(Asset).where(Asset.path == pulled).values(last_downloaded_at=None))
    await db.commit()
    # The tag, and never the manifest: a manifest is the format's own bookkeeping.
    assert await selected(db, settings, images) == [("", "app", "1.0")]

"""A tag removed by a cleanup run takes the image it named when nothing else names it
(cleanup spec 7.3); a tag deleted through the API still goes alone."""

from sqlalchemy import update

from megooarti.cleanup import run
from megooarti.clock import utcnow
from megooarti.repositories.docker import names
from megooarti.repositories.models import Asset
from tests.cleanup.conftest import attach, component_id, days_ago, paths_of
from tests.repositories.docker.conftest import (
    digest_of,
    index_manifest,
    push_image,
    push_manifest,
)


async def aged(db, *paths: str) -> None:
    await db.execute(update(Asset).where(Asset.path.in_(paths)).values(updated_at=days_ago(40)))
    await db.commit()


async def removing(db, settings, images, tag: str) -> str | None:
    context = await run.unattended_context(db, settings, images)
    removed = await run.remove(context, await component_id(db, images, "app", tag), utcnow())
    await db.commit()
    return removed


async def test_a_removed_tag_takes_its_image(client, root, db, settings, images):
    manifest = await push_image(client, root, "app", "1.0", "layer one")
    await aged(db, names.tag_path("app", "1.0"))
    await attach(db, images)

    removed = await removing(db, settings, images, "1.0")

    assert removed == "old"
    left = await paths_of(db, images)
    assert names.manifest_path("app", digest_of(manifest)) not in left
    assert [path for path in left if not path.startswith("blobs/")] == []


async def test_an_image_another_tag_names_is_kept(client, root, db, settings, images):
    manifest = await push_image(client, root, "app", "old", "layer one")
    await push_manifest(client, root, "app", "new", manifest)
    await aged(db, names.tag_path("app", "old"))
    await attach(db, images)

    removed = await removing(db, settings, images, "old")

    assert removed == "old"
    left = await paths_of(db, images)
    assert names.tag_path("app", "old") not in left
    assert names.tag_path("app", "new") in left
    assert names.manifest_path("app", digest_of(manifest)) in left


async def test_a_platform_image_of_an_index_is_kept(client, root, db, settings, images):
    platform = await push_image(client, root, "app", "amd", "layer one")
    listed = index_manifest(platform)
    assert (await push_manifest(client, root, "app", "multi", listed)).status_code == 201
    await aged(db, names.tag_path("app", "amd"))
    await attach(db, images)

    removed = await removing(db, settings, images, "amd")

    assert removed == "old"
    left = await paths_of(db, images)
    assert names.tag_path("app", "amd") not in left
    assert names.manifest_path("app", digest_of(platform)) in left


async def test_deleting_a_tag_through_the_api_still_leaves_its_image(client, root, db, images):
    manifest = await push_image(client, root, "app", "1.0", "layer one")
    found = await component_id(db, images, "app", "1.0")

    deleted = await client.delete(f"/api/v1/content/images/components/{found}", headers=root)

    assert deleted.status_code == 204
    assert names.manifest_path("app", digest_of(manifest)) in await paths_of(db, images)

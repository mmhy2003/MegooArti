"""Deleting from a Docker repository through the content API, as the registry API deletes."""

from sqlalchemy import select

from megooarti.repositories.models import Asset
from tests.accounts import error_code
from tests.repositories.docker.conftest import (
    V2,
    config_for,
    digest_of,
    layer,
    push_blob,
    push_image,
)

CONTENT = "/api/v1/content/images"


async def delete_file(client, root, path: str):
    return await client.delete(f"{CONTENT}/asset", params={"path": path}, headers=root)


async def stored(db) -> set[str]:
    return set(await db.scalars(select(Asset.path)))


async def test_deleting_a_tag_removes_the_tag_alone(client, images, root, db):
    manifest = await push_image(client, root, "team/app", "1.0", "one")

    deleted = await delete_file(client, root, "tags/team/app/1.0")
    by_tag = await client.get(f"{V2}/team/app/manifests/1.0", headers=root)
    by_digest = await client.get(f"{V2}/team/app/manifests/{digest_of(manifest)}", headers=root)

    assert deleted.status_code == 204
    assert (by_tag.status_code, by_digest.content) == (404, manifest)


async def test_deleting_a_manifest_removes_its_tags_and_what_only_it_used(client, images, root, db):
    old = await push_image(client, root, "team/app", "1.0", "base", "old")
    await push_image(client, root, "team/app", "2.0", "base", "new")
    await client.put(
        f"{V2}/team/app/manifests/stable",
        content=old,
        headers={**root, "Content-Type": "application/vnd.oci.image.manifest.v1+json"},
    )

    deleted = await delete_file(client, root, f"manifests/team/app/{digest_of(old)}")
    left = await stored(db)
    tags = await client.get(f"{V2}/team/app/tags/list", headers=root)

    assert deleted.status_code == 204
    assert tags.json()["tags"] == ["2.0"]  # both tags that named it went
    assert f"blobs/{digest_of(layer('old'))}" not in left
    assert f"blobs/{digest_of(config_for('base', 'old'))}" not in left
    assert f"blobs/{digest_of(layer('base'))}" in left  # the other image uses it
    pulled = await client.get(f"{V2}/team/app/manifests/2.0", headers=root)
    assert pulled.status_code == 200


async def test_a_layer_an_image_uses_does_not_go_by_itself(client, images, root, db):
    await push_image(client, root, "team/app", "1.0", "one")
    stray = await push_blob(client, root, "team/app", layer("never used"))

    used = await delete_file(client, root, f"blobs/{digest_of(layer('one'))}")
    unused = await delete_file(client, root, f"blobs/{stray}")

    assert (used.status_code, error_code(used)) == (409, "managed_by_format")
    assert unused.status_code == 204
    left = await stored(db)
    assert f"blobs/{digest_of(layer('one'))}" in left and f"blobs/{stray}" not in left


async def test_a_tag_is_deleted_as_a_component(client, images, root):
    await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "team/app", "2.0", "one")
    listed = await client.get(f"{CONTENT}/components", headers=root)
    first = next(item for item in listed.json()["items"] if item["version"] == "1.0")

    deleted = await client.delete(f"{CONTENT}/components/{first['id']}", headers=root)
    tags = await client.get(f"{V2}/team/app/tags/list", headers=root)

    assert deleted.status_code == 204
    assert tags.json()["tags"] == ["2.0"]


async def test_an_image_is_deleted_as_the_folder_of_its_manifests(client, images, root, db):
    await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "team/app", "2.0", "two")
    await push_image(client, root, "team/other", "1.0", "three")

    response = await client.delete(
        f"{CONTENT}/tree", params={"path": "manifests/team/app"}, headers=root
    )

    assert response.json() == {"deleted": 2, "skipped": 0, "next": None}
    left = await stored(db)
    assert {path for path in left if "team/app" in path} == set()  # tags too
    assert f"blobs/{digest_of(layer('one'))}" not in left
    assert f"blobs/{digest_of(layer('three'))}" in left
    assert (await client.get(f"{V2}/team/other/manifests/1.0", headers=root)).status_code == 200


async def test_the_blobs_folder_gives_up_only_what_no_image_uses(client, images, root, db):
    await push_image(client, root, "team/app", "1.0", "one")
    stray = await push_blob(client, root, "team/app", layer("never used"))

    response = await client.delete(f"{CONTENT}/tree", params={"path": "blobs"}, headers=root)

    assert response.json() == {"deleted": 1, "skipped": 2, "next": None}
    assert f"blobs/{stray}" not in await stored(db)
    assert (await client.get(f"{V2}/team/app/manifests/1.0", headers=root)).status_code == 200
